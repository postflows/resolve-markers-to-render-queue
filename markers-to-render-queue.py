# ================================================
# Markers to Render Queue
# Part of PostFlows toolkit for DaVinci Resolve
# https://github.com/postflows
# ================================================

"""
Markers to Render Queue — batch add clips with timeline markers to the render queue.

Description:
GUI for adding clips at marker positions to the render queue. Filter by marker color and type
(Single or Duration). Custom naming with components (Project/Timeline/Marker name, shotID, task, version),
naming presets, optional folder-per-render. Supports render preset naming or custom filenames.

Key features:
- Filter markers by color or process all
- Single markers: render entire clip at marker
- Duration markers: render only the marker's frame range (with validation)
- Single → Next Marker: render range from marker to the next marker (any color/type), last marker to timeline end
- Single → Next Same Color: render range from marker to the next marker with the same selected color, last marker to timeline end
- Naming: components (ProjectName, TimelineName, MarkerName, etc.), shotID (auto/reel/source), task, version
- Save/load naming presets
- Timeline and video track selection; markers table with double-click to jump to timecode
- Export path history; optional subfolder per render (for EXR sequences)

Requirements: DaVinci Resolve Studio; open project and timeline; defined render preset.

Usage: Select timeline, marker color and type, render preset. Configure naming (or use preset filename).
Choose export path. Click Add to Render Queue.

Author: Sergey Knyazkov
"""

import sys
import os
import csv
import json
from datetime import datetime
import re


################################################################################################
# GLOBAL VARIABLES AND INITIALIZATION
################################################################################################

# Initialize UI manager and dispatcher
ui = fu.UIManager
disp = bmd.UIDispatcher(ui)

DEBUG_MODE = False
# List of available marker colors
color_lst = [
    'All', 'Blue', 'Cyan', 'Green', 'Yellow', 'Red', 'Pink', 'Purple',
    'Fuchsia', 'Rose', 'Lavender', 'Sky', 'Mint', 'Lemon', 'Sand', 'Cocoa', 'Cream'
]

class SMPTE(object):
    '''Frames to SMPTE timecode converter and reverse.'''
    
    def __init__(self):
        self.fps = 24
        self.df = False
    
    def getframes(self, tc):
        '''Converts SMPTE timecode to frame count.'''
        if int(tc[9:]) > self.fps:
            raise ValueError('SMPTE timecode to frame rate mismatch.', tc, self.fps)
        
        hours = int(tc[:2])
        minutes = int(tc[3:5])
        seconds = int(tc[6:8])
        frames = int(tc[9:])
        
        totalMinutes = int(60 * hours + minutes)
        
        if self.df:  # Drop frame calculation
            dropFrames = int(round(self.fps * 0.066666))
            timeBase = int(round(self.fps))
            frm = int(((hourFrames * hours) + (minuteFrames * minutes) + (timeBase * seconds) + frames) - (dropFrames * (totalMinutes - (totalMinutes // 10))))
              
        else:  # Non-drop frame
            self.fps = int(round(self.fps))
            frm = int((totalMinutes * 60 + seconds) * self.fps + frames)
        
        return frm
    
    def gettc(self, frames):
        '''Converts frame count to SMPTE timecode.'''
        frames = abs(frames)
        
        if self.df:  # Drop frame calculation
            spacer, spacer2 = ':', ';'
            dropFrames = int(round(self.fps * .066666))
            framesPerHour = int(round(self.fps * 3600))
            framesPer10Minutes = int(round(self.fps * 600))
            framesPerMinute = int(round(self.fps) * 60 - dropFrames)
            
            frames = frames % (framesPerHour * 24)
            d = frames // framesPer10Minutes
            m = frames % framesPer10Minutes
            
            if m > dropFrames:
                frames += (dropFrames * 9 * d) + dropFrames * ((m - dropFrames) // framesPerMinute)
            else:
                frames += dropFrames * 9 * d
            
            frRound = int(round(self.fps))
            hr = frames // frRound // 3600
            mn = (frames // frRound // 60) % 60
            sc = (frames // frRound) % 60
            fr = frames % frRound
        else:  # Non-drop frame
            spacer = spacer2 = ':'
            self.fps = int(round(self.fps))
            frHour = self.fps * 3600
            frMin = self.fps * 60
            
            hr = frames // frHour
            mn = (frames - hr * frHour) // frMin
            sc = (frames - hr * frHour - mn * frMin) // self.fps
            fr = int(round(frames - hr * frHour - mn * frMin - sc * self.fps))
        
        return f"{hr:02d}{spacer}{mn:02d}{spacer}{sc:02d}{spacer2}{fr:02d}"

# Initialize Resolve project and timeline
projectManager = resolve.GetProjectManager()
project = projectManager.GetCurrentProject()
timeline = project.GetCurrentTimeline(1)

# After timeline is available
smpte = SMPTE()
smpte.fps = float(timeline.GetSetting('timelineFrameRate')) if timeline else 24.0

# Settings directory: subfolder next to this script (user can find, edit, delete)
try:
    _script_dir = os.path.dirname(os.path.abspath(__file__))
except NameError:
    _script_dir = os.path.expanduser('~')
SETTINGS_DIR = os.path.join(_script_dir, 'RMT Markers_to_render_queue_settings')
PRESETS_FILE = os.path.join(SETTINGS_DIR, 'naming_presets.json')
SETTINGS_FILE = os.path.join(SETTINGS_DIR, 'render_paths.json')


def _ensure_settings_dir():
    """Create settings directory if it does not exist."""
    if not os.path.isdir(SETTINGS_DIR):
        try:
            os.makedirs(SETTINGS_DIR, exist_ok=True)
        except Exception as e:
            debug_print(f"Error creating settings dir: {e}")


def load_render_paths():
    """
    Loads the saved render paths from the settings file.
    Returns a list of paths, with home directory as default if no paths are saved.
    """
    try:
        if os.path.exists(SETTINGS_FILE):
            with open(SETTINGS_FILE, 'r') as f:
                return json.load(f)
    except Exception as e:
        debug_print(f"Error loading render paths: {e}")
    return [os.path.expanduser('~')]


def save_render_paths(paths):
    """
    Saves the render paths to the settings file.
    """
    try:
        _ensure_settings_dir()
        with open(SETTINGS_FILE, 'w') as f:
            json.dump(paths, f)
    except Exception as e:
        debug_print(f"Error saving render paths: {e}")

def update_render_paths(new_path):
    """
    Updates the list of render paths, maintaining the most recent 3 paths.
    """
    paths = load_render_paths()
    if new_path in paths:
        paths.remove(new_path)
    paths.insert(0, new_path)
    paths = paths[:3]  # Keep only the last 3 paths
    save_render_paths(paths)
    return paths


# Style for the primary action button
PRIMARY_ACTION_BUTTON_STYLE = """
    QPushButton {
        border: 1px solid #2C6E49;
        max-height: 28px;
        border-radius: 14px;
        background-color: #4C956C;
        color: #FFFFFF;
        min-height: 28px;
        font-size: 13px;
    }
    QPushButton:hover {
        border: 1px solid #c0c0c0;
        background-color: #61B15A;
    }
    QPushButton:pressed {
        border: 2px solid  #c0c0c0;
        background-color:  #76C893;
    }
    QPushButton:disabled {
        border: 2px solid #8c2f39;
        background-color: rgb(50,50,50);
        color: rgb(150, 150, 150);
    }
"""
DIVIDER_CSS = """
    background-color: #555;
    border: none;
    height: 1px; 
    max-height: 1px;
    margin: 3px 0;
"""

# Styles for export path labels
WARNING_PATH_STYLE = "color: rgb(255, 0, 0); font-weight: bold;"
NORMAL_PATH_STYLE = "color: rgb(176, 176, 176);"

################################################################################################
# UI FUNCTIONS
################################################################################################

def debug_print(*args, **kwargs):
    """
    Wrapper function for debug printing. Prints the provided arguments if DEBUG_MODE is enabled.

    Args:
        *args: Variable length argument list.
        **kwargs: Arbitrary keyword arguments.
    """
    if DEBUG_MODE:
        print(*args, **kwargs)

def update_status(message):
    """
    Updates the status line in the UI.
    """
    itm["status_label"].Text = message
    itm["status_label"].Update()

def main_ui():
    """
    Creates and returns the main UI layout for the script.

    Returns:
        UI Group: The main UI layout containing all controls and settings.
    """
    return ui.VGroup({"Spacing": 10}, [
        # Marker and Timeline Selection
        ui.VGroup({"Spacing": 5}, [
            ui.HGroup({"Spacing": 5}, [
                ui.Label({"Text": "Timeline:", "Weight": 0}),
                # Read-only: this tool always works with the timeline that was
                # active in Resolve when it was launched (see "timeline" global).
                ui.Label({"ID": "tl_preset_label", "Text": "", "StyleSheet": "font-weight: bold;", "Weight": 1}),
                ui.Label({"Text": "Marker Color:", "Weight": 0}),
                ui.ComboBox({"ID": "marker_color", "Weight": 2})
            ]),
            ui.HGroup({"Spacing": 5}, [
                ui.Label({"Text": "Video Track:", "Weight": 0}),
                ui.ComboBox({"ID": "video_track", "Weight": 3})
            ]),
            ui.HGroup({"Spacing": 5}, [
                ui.Label({"Text": "Marker Type:", "Weight": 0}),
                ui.ComboBox({"ID": "marker_type", "Items": ["Single", "Duration", "Single → Next Marker", "Single → Next Same Color"], "CurrentText": "Single"})
            ])
         
        ]),

        # Markers Table
        ui.Tree({
            "ID": "markers_table",
            "HeaderText": " |Timecode|Color|Name|Source Name|Clip Name|Note|Reel Name",
            "ColumnCount": 8,
            "ColumnWidth": "26,170,110,150,190,190,140,100",
            "SelectionMode": "MultiSelection",
            "Weight": 15,
            "AlternatingRowColors": True,
            "InitialSortColumn": 1,
            "InitialSortOrder": "AscendingOrder",
            "SortingEnabled": True,
            "Events": {"ItemDoubleClicked": True, "ItemChanged": True}
        }),
        ui.HGroup({"Spacing": 5}, [
            ui.Label({"Text": "Tip: check a box to include only those markers when rendering. Double-click Color/Name/Note to edit.", "StyleSheet": "color: #999999; font-size: 11px;", "Weight": 3}),
            ui.Button({"ID": "delete_markers_btn", "Text": "Delete Checked", "Weight": 1}),
            ui.Button({"ID": "clear_selection_btn", "Text": "Clear Checks", "Weight": 1})
        ]),

        # Render Settings
        ui.VGroup({"Spacing": 5}, [
            ui.HGroup({"Spacing": 5}, [
                ui.Label({"Text": "Render Preset:", "Weight": 1}),
                ui.ComboBox({"ID": "render_preset", "Weight": 3})
            ]),
            ui.HGroup({"Spacing": 5}, [
                ui.CheckBox({
                    "ID": "use_preset_naming", 
                    "Text":  "📋 Use filename from current render preset",
                    "StyleSheet": "font-size: 14px;",
                    "Checked": False
                }),
            ])
        ]),

        # Naming Settings
        ui.Label({
            # "StyleSheet": DIVIDER_CSS,
            "Weight": 0,
            "FrameStyle": 4,
            "Margin": -5
        }),        
        ui.VGroup({"Spacing": 10, "StyleSheet": "font-weight: bold;", }, [
            ui.Label({"ID": "Custom Naming Settings", "Text": "Custom Naming Settings", "StyleSheet": "font-size: 14px;"}),
            
            # Shot Fields
            ui.VGroup({"Spacing": 5}, [
                ui.Label({"Text": "Naming Components", "StyleSheet": "font-weight: bold;"}),
                
                # Component1
                ui.HGroup({"Spacing": 5}, [
                    ui.CheckBox({"ID": "component1_enabled", "Text": "Component 1", "Checked": True}),
                    ui.ComboBox({
                        "ID": "component1_source",
                        "Items": ["ProjectName", "TimelineName", "MarkerName", "MarkerNote", "Reel Name", "SourceName", "ClipName", "Custom"]
                    }),
                    ui.LineEdit({
                        "ID": "component1_custom",
                        "PlaceholderText": "Custom value",
                        "Enabled": False
                    })
                ]),
                
                # Component2
                ui.HGroup({"Spacing": 5}, [
                    ui.CheckBox({"ID": "component2_enabled", "Text": "Component 2", "Checked": True}),
                    ui.ComboBox({
                        "ID": "component2_source",
                        "Items": ["ProjectName", "TimelineName", "MarkerName", "MarkerNote", "Reel Name", "SourceName", "ClipName", "Custom"]
                    }),
                    ui.LineEdit({
                        "ID": "component2_custom",
                        "PlaceholderText": "Custom value",
                        "Enabled": False
                    })
                ]),
                
                # Component3
                ui.HGroup({"Spacing": 5}, [
                    ui.CheckBox({"ID": "component3_enabled", "Text": "Component 3"}),
                    ui.ComboBox({
                        "ID": "component3_source",
                        "Items": ["ProjectName", "TimelineName", "MarkerName", "MarkerNote", "Reel Name", "SourceName", "ClipName", "Custom"]
                    }),
                    ui.LineEdit({
                        "ID": "component3_custom",
                        "PlaceholderText": "Custom value",
                        "Enabled": False
                    })
                ]),
                
                # ShotID
                ui.HGroup({"Spacing": 5}, [
                    ui.CheckBox({"ID": "shotID_enabled", "Text": "shotID", "Checked": True}),
                    ui.ComboBox({
                        "ID": "shotID_source",
                        "Items": ["Auto Number", "Reel Name", "SourceName", "ClipName", "MarkerName", "MarkerNote"],
                        "Weight": 2
                    }),
                    ui.Label({"Text": "Start:", "Weight": 0}),
                    ui.SpinBox({"ID": "shotID_start", "Value": 10, "Minimum": 1, "MaximumWidth": 70}),
                    ui.Label({"Text": "Step:", "Weight": 0}),
                    ui.SpinBox({"ID": "shotID_step", "Value": 10, "Minimum": 1, "MaximumWidth": 70}),
                    ui.Label({"Text": "Padding:", "Weight": 0}),
                    ui.SpinBox({"ID": "shotID_padding", "Value": 4, "Minimum": 1, "MaximumWidth": 70})
                ])
            ]),
            
            # Version Fields
            ui.VGroup({"Spacing": 5}, [
                ui.Label({"Text": "Version Fields", "StyleSheet": "font-weight: bold;"}),
                
                # Task
                ui.HGroup({"Spacing": 5}, [
                    ui.CheckBox({"ID": "task_enabled", "Text": "task", "Checked": False}),
                    ui.ComboBox({
                        "ID": "task_source",
                        "Items": ["comp", "anim", "roto", "match", "paint", "Custom"]
                    }),
                    ui.LineEdit({
                        "ID": "task_custom",
                        "PlaceholderText": "Custom value",
                        "Enabled": False
                    })
                ]),
                
                # Version
                ui.HGroup({"Spacing": 5}, [
                    ui.CheckBox({"ID": "version_enabled", "Text": "version", "Checked": True}),
                    ui.Label({"Text": "Prefix:"}),
                    ui.LineEdit({"ID": "version_prefix", "Text": "v", "Weight": 1}),
                    ui.Label({"Text": "Start:"}),
                    ui.SpinBox({"ID": "version_start", "Value": 1, "Minimum": 1, "Weight": 1}),
                    ui.Label({"Text": "Padding:"}),
                    ui.SpinBox({"ID": "version_padding", "Value": 3, "Minimum": 1, "Weight": 1})
                ])
            ]),

        ]),
        ui.HGroup({"Spacing": 5}, [
            ui.Label({"Text": "Naming Presets:", "Weight": 0}),
            ui.ComboBox({"ID": "naming_presets", "Weight": 2}),
            ui.LineEdit({"ID": "preset_name_input", "PlaceholderText": "Enter preset name", "Weight": 2}),
            ui.Button({"ID": "save_preset", "Text": "Save", "Weight": 1}),
            ui.Button({"ID": "load_preset", "Text": "Load", "Weight": 1}),
            ui.Button({"ID": "delete_preset", "Text": "Delete", "Weight": 1})
        ]),
        ui.Label({
            # "StyleSheet": DIVIDER_CSS,
            "Weight": 0,
            "FrameStyle": 4
        }),
        ui.Label({
            "ID": "status_label",
            "Text": "Ready",
            "StyleSheet": "color: #686A6C; font-style: italic;"
        }),        
        # Export Settings
        ui.VGroup({"Spacing": 10}, [
            ui.HGroup({"Spacing": 5}, [
                ui.Label({"Text": "Export to:", "StyleSheet": "font-size: 16px; font-weight: bold;",  "Weight": 1}),
                ui.HGroup({"Spacing": 5, "Weight": 5}, [
                    ui.ComboBox({
                        "ID": "export_path",
                        "StyleSheet": "color: rgb(176, 176, 176);",
                        "Weight": 3,
                        "Editable": True
                    }),
                    ui.Button({
                        "ID": "export_location", 
                        "Text": "Select Path",
                        "StyleSheet": """
                            QPushButton {
                                border: 1px solid rgb(176,176,176);
                                max-height: 24px;
                                border-radius: 10px;
                                background-color: rgb(71,91,98);
                                color: rgb(255, 255, 255);
                                min-height: 24px;
                                font-size: 13px;
                            }
                            QPushButton:hover {
                                border: 1px solid rgb(176,176,176);
                                background-color: rgb(89,90,183);
                            }
                            QPushButton:pressed {
                                border: 2px solid rgb(119,121,252);
                                background-color: rgb(119,121,252);
                            }
                            QPushButton:disabled {
                                border: 2px solid #8c2f39;
                                background-color: rgb(50,50,50);
                                color: rgb(150, 150, 150);
                            }
                        """
                    })
                ])
            ]),
            ui.VGroup({"Spacing": 5}, [
                ui.CheckBox({
                    "ID": "create_folders", 
                    "Text":  "📁 Create separate folder for each render (based on filename)",
                    "StyleSheet": "font-size: 13px;",
                    "Checked": False,
                    "ToolTip": "Creates a subfolder for each render job with the same name as the output file. Essential for EXR sequences."
                })
            ]),


        ]),

        # Export Button
        ui.HGroup({"Spacing": 5}, [
            ui.Label({"Text": "Preview:", "StyleSheet": "font-size: 16px; font-weight: bold;", "Weight": 0}),
            ui.Label({"ID": "naming_preview", "Text": "SHOW_EP01_SH010_comp_v001", "StyleSheet": "color: #469BE6; font-size: 14px; qproperty-alignment: AlignLeft",  "Weight": 5}),          
            
        ]),
        ui.Label({"ID": "naming_format", "Text": "Format: showID_episode_shotID_task_version"}),
        ui.Button({
            "ID": "Export", 
            "Text": "Add to Render Queue", 
            "StyleSheet": PRIMARY_ACTION_BUTTON_STYLE,
            "Enabled": True
        })
    ])

_WINDOWS_RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9",
    "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9",
}


def sanitize_filename(s):
    """
    Replaces invalid filename characters with underscore, strips trailing
    dots/spaces, and avoids Windows-reserved device names (CON, PRN, NUL,
    COM1-9, LPT1-9) — needed if renders end up on storage that's also read
    from Windows machines, since these can otherwise produce a name that's
    invalid or behaves oddly on that OS.
    """
    if not isinstance(s, str):
        return s
    result = re.sub(r'[<>:"/\\|?*]', '_', s)
    result = result.rstrip('. ')
    if result.upper() in _WINDOWS_RESERVED_NAMES:
        result = f"{result}_"
    return result

def _format_fps_value(fps_value):
    """
    Formats FPS value for filenames (e.g. 24, 23.976).
    """
    try:
        fps_float = float(fps_value)
        if fps_float.is_integer():
            return str(int(fps_float))
        s = f"{fps_float:.3f}"
        return s.rstrip('0').rstrip('.')
    except Exception:
        return str(fps_value) if fps_value is not None else ""

_render_preset_format_codec_cache = {}


def _get_render_preset_format_codec(proj, preset_name):
    """
    Returns (format, codec) for the given render preset name.
    The values are read after loading the preset into the project.

    Cached per preset name for the life of the script: this gets called once
    per naming component per marker, and reloading the same preset from disk
    every time is wasted work (this tool already loads the selected preset
    once up front in _main() before any of this runs).
    """
    if preset_name in _render_preset_format_codec_cache:
        return _render_preset_format_codec_cache[preset_name]

    try:
        if preset_name:
            proj.LoadRenderPreset(preset_name)
        info = proj.GetCurrentRenderFormatAndCodec() or {}
        fmt = info.get("format", "") or ""
        codec = info.get("codec", "") or ""

        # Fallback: some presets (e.g. certain H.265 variants) may not populate "codec" here.
        if not codec:
            try:
                settings = proj.GetRenderSettings() or {}
                for key in (
                    "Codec", "codec",
                    "VideoCodec", "videoCodec",
                    "VideoCodecName", "videoCodecName",
                    "OutputCodec", "outputCodec",
                ):
                    value = settings.get(key)
                    if isinstance(value, str) and value.strip():
                        codec = value.strip()
                        break
            except Exception as e:
                debug_print(f"RenderSettings codec fallback failed: {str(e)}")

        # Last-resort fallback: infer codec from preset name when API doesn't expose it.
        # (Some Resolve builds return codec="" for H.265 presets in GetCurrentRenderFormatAndCodec.)
        if not codec and preset_name:
            name = str(preset_name).lower()
            if "h.265" in name or "h265" in name or "hevc" in name:
                codec = "H265"
            elif "h.264" in name or "h264" in name or "avc" in name:
                codec = "H264"

        result = (fmt, codec)
        _render_preset_format_codec_cache[preset_name] = result
        return result
    except Exception as e:
        error_msg = f"Warning: failed to read render format/codec: {str(e)}"
        update_status(error_msg)
        print(error_msg)
        result = ("", "")
        _render_preset_format_codec_cache[preset_name] = result
        return result

def get_component_value(component_settings, clip_info, example_data, default_value, counter=0):
    """
    Returns the value for a naming component; used for preview and for generating filenames.

    Args:
        component_settings (dict): Component settings
        clip_info (dict): Clip information
        example_data (dict): Data from markers table
        default_value (str): Default value
        counter (int): Counter for auto-numbering

    Returns:
        str: Component value
    """
    if not component_settings["enabled"]:
        return None
        
    source = component_settings["source"]
    
    if source == "ProjectName":
        return sanitize_filename(project.GetName() or default_value)
    elif source == "TimelineName":
        return sanitize_filename(timeline.GetName() or default_value)
    elif source == "TimelineFPS":
        fps = timeline.GetSetting("timelineFrameRate")
        return sanitize_filename(_format_fps_value(fps) or default_value)
    elif source == "TimelineResolution":
        w = timeline.GetSetting("timelineResolutionWidth")
        h = timeline.GetSetting("timelineResolutionHeight")
        if w and h:
            return sanitize_filename(f"{w}x{h}")
        return sanitize_filename(default_value)
    elif source == "RenderFormat":
        preset_name = itm["render_preset"].CurrentText
        fmt, _codec = _get_render_preset_format_codec(project, preset_name)
        return sanitize_filename(fmt or default_value)
    elif source == "RenderCodec":
        preset_name = itm["render_preset"].CurrentText
        _fmt, codec = _get_render_preset_format_codec(project, preset_name)
        return sanitize_filename(codec or default_value)
    elif source == "RenderFormatCodec":
        preset_name = itm["render_preset"].CurrentText
        fmt, codec = _get_render_preset_format_codec(project, preset_name)
        value = "_".join([v for v in [fmt, codec] if v])
        return sanitize_filename(value or default_value)
    elif source == "MarkerName":
        return sanitize_filename(example_data.get('marker_name', default_value))
    elif source == "MarkerNote":
        return sanitize_filename(example_data.get('marker_note', default_value))
    elif source == "Reel Name":
        if clip_info and clip_info.get('media_pool_item'):
            reel = clip_info['media_pool_item'].GetClipProperty('Reel Name')
            return sanitize_filename(reel if reel else "REEL_ERR")
        return sanitize_filename(example_data.get('reel_name', default_value))
    elif source == "SourceName":
        if clip_info and clip_info.get('media_pool_item'):
            return sanitize_filename(clip_info['media_pool_item'].GetName() or default_value)
        return sanitize_filename(example_data.get('source_name', default_value))
    elif source == "ClipName":
        if clip_info and clip_info.get('clip'):
            clip_name = clip_info['clip'].GetName()
            return sanitize_filename(clip_name if clip_name else default_value)
        return sanitize_filename(default_value)
    elif source == "Custom":
        return sanitize_filename(component_settings["custom"] or default_value)
    elif source == "Auto Number":
        start = component_settings["start"]
        step = component_settings["step"]
        padding = component_settings["padding"]
        return f"{str(start + counter * step).zfill(padding)}"
    
    return sanitize_filename(default_value)

def update_naming_preview():
    """
    Updates the naming preview based on the current settings in the UI.
    """
    if not itm["use_preset_naming"].Checked:
        try:
            components = []
            current_settings = get_current_settings()

            # Get example data from the markers table
            table = itm["markers_table"]
            example_data = {}
            clip_info = None
            if table.TopLevelItemCount() > 0:
                first_item = table.TopLevelItem(0)
                example_data = {
                    'timecode': first_item.Text[1],
                    'source_name': first_item.Text[4],
                    'clip_name': first_item.Text[5],
                    'marker_name': first_item.Text[3],
                    'marker_note': first_item.Text[6],
                    'reel_name': first_item.Text[7]
                }

                # Get clip info at the marker frame
                try:
                    marker_frame = timeline.GetStartFrame() + int(first_item.Text[1].split(':')[-1])
                    clip_info = get_clip_at_marker(timeline, marker_frame)
                except:
                    clip_info = None

            # Component 1
            comp1 = get_component_value(current_settings["component1"], clip_info, example_data, "COMP1")
            if comp1:
                components.append(comp1)
                
            # Component 2
            comp2 = get_component_value(current_settings["component2"], clip_info, example_data, "COMP2")
            if comp2:
                components.append(comp2)
                
            # Component 3
            comp3 = get_component_value(current_settings["component3"], clip_info, example_data, "COMP3")
            if comp3:
                components.append(comp3)

            # ShotID
            if current_settings["shotID"]["enabled"]:
                shot_value = get_component_value(current_settings["shotID"], clip_info, example_data, "SHOT010", 0)
                if shot_value:
                    components.append(shot_value)

            # Task
            if current_settings["task"]["enabled"]:
                task_source = itm["task_source"].CurrentText
                components.append(task_source if task_source != "Custom" else current_settings["task"]["custom"] or "TASK")

            # Version
            if current_settings["version"]["enabled"]:
                version_prefix = current_settings["version"]["prefix"]
                version_pad = current_settings["version"]["padding"]
                version_num = str(current_settings["version"]["start"]).zfill(version_pad)
                components.append(f"{version_prefix}{version_num}")

            # Build the final preview
            separator = "_"
            example = separator.join(filter(None, components))
            format_text = separator.join([c for c in [
                "component1" if current_settings["component1"]["enabled"] else None,
                "component2" if current_settings["component2"]["enabled"] else None,
                "component3" if current_settings["component3"]["enabled"] else None,
                "shotID" if current_settings["shotID"]["enabled"] else None,
                "task" if current_settings["task"]["enabled"] else None,
                "version" if current_settings["version"]["enabled"] else None
            ] if c])

            itm["naming_preview"].Text = f"{example}" if example else "No components selected"
            itm["naming_format"].Text = f"Format: {format_text}" if format_text else "Invalid format"

        except Exception as e:
            print(f"Preview error: {str(e)}")
            itm["naming_preview"].Text = "Error in preview"
    else:
        itm["naming_preview"].Text = "Uncheck 'Use filename from current render preset' for custom filename"

# Create main window
window = disp.AddWindow({
    "WindowTitle": "Markers to Render Queue",
    "ID": "MTRWin", 
    'WindowFlags': {'Window': True, 'WindowStaysOnTopHint': True},
    "Geometry": [1000, 400, 775, 800],
}, main_ui())

# Get UI items for global access
itm = window.GetItems()

def get_current_settings():
    """
    Retrieves the current naming settings from the UI.

    Returns:
        dict: A dictionary containing all naming settings.
    """
    return {
        "component1": {
            "enabled": itm["component1_enabled"].Checked,
            "source": itm["component1_source"].CurrentText,
            "custom": itm["component1_custom"].Text
        },
        "component2": {
            "enabled": itm["component2_enabled"].Checked,
            "source": itm["component2_source"].CurrentText,
            "custom": itm["component2_custom"].Text
        },
        "component3": {
            "enabled": itm["component3_enabled"].Checked,
            "source": itm["component3_source"].CurrentText,
            "custom": itm["component3_custom"].Text
        },
        "shotID": {
            "enabled": itm["shotID_enabled"].Checked,
            "source": itm["shotID_source"].CurrentText,
            "start": itm["shotID_start"].Value,
            "step": itm["shotID_step"].Value,
            "padding": itm["shotID_padding"].Value
        },
        "task": {
            "enabled": itm["task_enabled"].Checked,
            "source": itm["task_source"].CurrentText,
            "custom": itm["task_custom"].Text
        },
        "version": {
            "enabled": itm["version_enabled"].Checked,
            "prefix": itm["version_prefix"].Text,
            "start": itm["version_start"].Value,
            "padding": itm["version_padding"].Value
        }
    }

################################################################################################
# MARKER AND TIMELINE MANAGEMENT
################################################################################################
    
def get_marker_type(marker):
    """
    Determines if a marker is single or duration type.
    
    Args:
        marker (dict): Marker data from timeline
        
    Returns:
        str: "single" or "duration"
    """
    # Check if marker has duration greater than 1 frame
    # Duration = 1 means it's a single frame marker (single type)
    # Duration > 1 means it's a duration marker
    if "duration" in marker:
        duration = marker.get("duration", 0)
        if duration > 1:
            debug_print(f"Duration marker found: {duration} frames")
            return "duration"
        else:
            debug_print(f"Single marker found: {duration} frame(s)")
            return "single"

    # Fallback: check for other duration indicators
    if "end" in marker and marker.get("end", 0) > marker.get("start", 0):
        debug_print("Duration marker found (end-start)")
        return "duration"

    debug_print("Single marker found (no duration info)")
    return "single"

def get_markers(tl):
    """
    Retrieves markers of the selected color and type from the timeline.

    Args:
        tl (Timeline): The timeline object to search for markers.

    Returns:
        tuple: A tuple containing:
            - A list of marker positions.
            - A dictionary of all markers with their details.
    """
    color_text = itm["marker_color"].CurrentText
    color = color_text.split(" (")[0]
    marker_type = "duration" if itm["marker_type"].CurrentText == "Duration" else "single"
    debug_print(f"Looking for {color} {marker_type} markers")

    markers = tl.GetMarkers()
    color_markers = []

    for frame, marker in markers.items():
        # Check color filter
        if color != "All" and marker.get("color") != color:
            continue
            
        # Check marker type filter
        if get_marker_type(marker) != marker_type:
            continue
            
        color_markers.append(frame)

    if not color_markers:
        no_markers_msg = f"No {color} {marker_type} markers found"
        update_status(no_markers_msg)
        print(f"ERROR: {no_markers_msg}")

    return sorted(color_markers), markers


def get_used_marker_colors(timeline):
    """
    Retrieves a list of marker colors with their counts used in the timeline.

    Args:
        timeline (Timeline): The timeline object to analyze.

    Returns:
        list: A list of colors with their counts in the format "Color (Count)".
    """
    if not timeline:
        return ["All (0)"]

    markers = timeline.GetMarkers()
    color_counts = {}

    for marker in markers.values():
        if "color" in marker:
            color = marker["color"]
            color_counts[color] = color_counts.get(color, 0) + 1

    color_list = [f"All ({len(markers)})"]
    color_list.extend(f"{color} ({count})" for color, count in sorted(color_counts.items()))

    return color_list


def get_session_timeline_name():
    """
    Returns the name of the timeline this session is locked to (the one that
    was active in Resolve when the script was launched — see the "timeline"
    global), or None if there wasn't one.
    """
    return timeline.GetName() if timeline else None

def validate_frame_range(in_point, out_point, timeline):
    """
    Validate and adjust frame range if necessary
    
    Args:
        in_point (int): Start frame
        out_point (int): End frame
        timeline (Timeline): Timeline object
        
    Returns:
        tuple: (validated_in, validated_out) or (None, None) if invalid
    """
    timeline_start = timeline.GetStartFrame()
    timeline_end = timeline.GetEndFrame()
    
    # Adjust values if they go beyond timeline boundaries
    in_point = max(timeline_start, in_point)
    out_point = min(timeline_end, out_point)
    
    # Check range validity
    if in_point >= out_point:
        print(f"Warning: Invalid frame range: {in_point} to {out_point}")
        return None, None
        
    return in_point, out_point

def get_duration_marker_range(marker):
    """
    Gets the render range for a duration marker.
    
    Args:
        marker (dict): Duration marker data
        
    Returns:
        tuple: (start_frame, end_frame)
    """
    # For duration markers, we need to calculate the range
    # The marker position is the start, duration is the length
    start_frame = marker.get("start", 0)
    duration = marker.get("duration", 0)
    
    # Duration markers should have duration > 1
    if duration <= 1:
        print(f"Warning: Duration marker has duration <= 1: {duration}")
        return start_frame, start_frame + 1
    
    end_frame = start_frame + duration
    debug_print(f"Duration marker range: {start_frame} - {end_frame} ({duration} frames)")
    return start_frame, end_frame

def get_sorted_marker_frames(markers):
    """
    Returns marker frames sorted by their position on timeline
    """
    sorted_frames = sorted(markers)
    if DEBUG_MODE:
        print("Sorted marker frames:")
        for frame in sorted_frames:
            print(f"Frame position: {frame}")
    return sorted_frames

def analyze_timeline_tracks(timeline, marker_frame):
    """
    Analyzes presence of video and audio clips on the timeline.

    Returns:
        tuple: (has_video, has_audio, video_info, audio_info)
    """
    video_clips = []
    audio_clips = []

    # Check video tracks
    video_track_count = timeline.GetTrackCount("video")
    for track_index in range(video_track_count):
        track = timeline.GetItemListInTrack("video", track_index + 1)
        for clip in track:
            if clip.GetMediaPoolItem():
                video_clips.append({
                    'track': track_index + 1,
                    'count': len(track)
                })
                break
    
    # Check audio tracks only if no video
    if not video_clips:
        audio_track_count = timeline.GetTrackCount("audio")
        for track_index in range(audio_track_count):
            track = timeline.GetItemListInTrack("audio", track_index + 1)
            for clip in track:
                if clip.GetMediaPoolItem():
                    audio_clips.append({
                        'track': track_index + 1,
                        'count': len(track)
                    })
                    break
    
    return bool(video_clips), bool(audio_clips), video_clips, audio_clips

################################################################################################
# CLIP MANAGEMENT
################################################################################################
def process_track_clips(track, track_index, marker_frame, track_type):
    """
    Processes clips on the track and finds the clip at the given marker position.

    Args:
        track: Track to process
        track_index: Track index
        marker_frame: Marker frame
        track_type: Track type ("video" or "audio")

    Returns:
        dict: Found clip info or None
    """
    for clip in track:
        clip_start_timeline = clip.GetStart()
        clip_end_timeline = clip_start_timeline + clip.GetDuration() - 1
        
        media_pool_item = clip.GetMediaPoolItem()
        if media_pool_item and clip_start_timeline <= marker_frame <= clip_end_timeline:
            return {
                'clip': clip,
                'timeline_start': clip_start_timeline,
                'timeline_end': clip_end_timeline,
                'clip_in': clip.GetLeftOffset(),
                'clip_out': clip.GetLeftOffset() + clip.GetDuration() - 1,
                'duration': clip.GetDuration(),
                'track': track_index + 1,
                'track_type': track_type,
                'media_pool_item': media_pool_item
            }
    return None

def get_clip_at_marker(timeline, marker_frame, has_video_audio=None):
    """
    Args:
        has_video_audio: optional (has_video, has_audio) tuple, precomputed
            once by the caller via analyze_timeline_tracks(), to avoid
            rescanning every track on the timeline for every single marker
            (analyze_timeline_tracks() doesn't actually use marker_frame —
            it just checks whether the timeline has any video/audio clips
            at all — so that result is the same for every marker and only
            needs to be computed once per export/table refresh).
    """
    if has_video_audio is not None:
        has_video, has_audio = has_video_audio
    else:
        has_video, has_audio, _video_tracks, _audio_tracks = analyze_timeline_tracks(timeline, marker_frame)
    
    if has_video:
        selected_track = itm["video_track"].CurrentText
        video_track_count = timeline.GetTrackCount("video")
        
        if selected_track != "Default (Topmost)":
            
            try:
                track_index = int(selected_track.split()[-1]) - 1  
                if 0 <= track_index < video_track_count:
                    track = timeline.GetItemListInTrack("video", track_index + 1)
                    clip_info = process_track_clips(track, track_index, marker_frame, "video")
                    if clip_info:
                        update_status(f"Processing video track {track_index + 1}")
                        return clip_info
                    else:
                        update_status(f"No clip found on selected Video Track {track_index + 1}")
                        return None
                else:
                    update_status(f"Invalid track index: {track_index + 1}")
                    return None
            except ValueError:
                update_status("Error parsing selected track")
                return None
        else:
            
            for track_index in range(video_track_count - 1, -1, -1):
                track = timeline.GetItemListInTrack("video", track_index + 1)
                clip_info = process_track_clips(track, track_index, marker_frame, "video")
                if clip_info:
                    update_status(f"Processing video track {track_index + 1}")
                    return clip_info
    elif has_audio:
        
        for track_index in range(timeline.GetTrackCount("audio")):
            track = timeline.GetItemListInTrack("audio", track_index + 1)
            clip_info = process_track_clips(track, track_index, marker_frame, "audio")
            if clip_info:
                update_status(f"Processing audio track {track_index + 1}")
                return clip_info
                
    return None

################################################################################################
# RENDER AND EXPORT
################################################################################################

def create_render_folder_path(base_path, filename, clip_info=None, all_markers=None):
    """
    Creates a folder path for render output based on filename and settings.
    
    Args:
        base_path (str): Base export directory
        filename (str): Generated filename for the render (empty if using preset naming)
        clip_info (dict): Information about the clip (optional)
        all_markers (dict): Dictionary with all markers (optional)
        
    Returns:
        str: Full path to the render folder
    """
    if not itm["create_folders"].Checked:
        return base_path
    
    try:
        # If filename is empty (preset naming), generate folder name from marker/clip info
        if not filename or filename.strip() == "":
            folder_name = "Render"
            if clip_info and clip_info.get('marker_frame') is not None:
                marker_frame = clip_info['marker_frame']
                if all_markers and marker_frame in all_markers:
                    marker_data = all_markers[marker_frame]
                    marker_name = marker_data.get('name', '')
                    if marker_name:
                        folder_name = sanitize_filename(marker_name)
                    else:
                        # Use marker note or generate from frame number
                        marker_note = marker_data.get('note', '')
                        if marker_note:
                            folder_name = sanitize_filename(marker_note)
                        else:
                            folder_name = f"Marker_{marker_frame}"
                else:
                    folder_name = f"Marker_{marker_frame}"
            elif clip_info and clip_info.get('media_pool_item'):
                # Fallback to source name
                source_name = clip_info['media_pool_item'].GetName()
                if source_name:
                    folder_name = sanitize_filename(source_name.rsplit('.', 1)[0] if '.' in source_name else source_name)
        else:
            # Clean filename - remove extension and trailing dot for EXR sequences
            folder_name = filename.rstrip('.')
            # Remove any file extension that might be present
            if '.' in folder_name:
                # For EXR sequences, filename ends with ".", so we just strip it
                # For other formats, remove the extension
                parts = folder_name.rsplit('.', 1)
                if len(parts) > 1 and parts[1] in ['mov', 'mp4', 'mxf', 'dpx', 'tiff', 'tif', 'jpg', 'jpeg', 'png', 'exr']:
                    folder_name = parts[0]
                else:
                    folder_name = folder_name.rstrip('.')
        
        # Sanitize folder name
        folder_name = sanitize_filename(folder_name)
        
        # Standard folder creation - just create folder with filename
        final_path = os.path.join(base_path, folder_name)
        os.makedirs(final_path, exist_ok=True)
        print(f"Created render folder: {final_path}")
        return final_path
        
    except Exception as e:
        error_msg = f"Error creating render folder: {str(e)}"
        print(error_msg)
        update_status(error_msg)
        # Return base path if folder creation fails
        return base_path

def update_export_button_state():
    """
    Updates the enabled state of the Export button based on the export path.

    If the export path is set and not empty, the Export button is enabled.
    Otherwise, it is disabled.
    """
    export_path = itm["export_path"].CurrentText
    itm["Export"].Enabled = bool(export_path and export_path.strip()) and bool(timeline)


def get_filenames(markers, all_markers, counter_by_mark=None):
    """
    Args:
        counter_by_mark: optional {frame: index} map used for Auto Number, so
            numbering reflects each marker's position among ALL markers
            matching the current filter rather than just this call's
            (possibly checkbox-reduced) `markers` list. Falls back to
            numbering within `markers` itself if not given.
    """
    if itm["use_preset_naming"].Checked:
        return {}
        
    filename_map = {}
    
    # The render preset is already loaded and validated once, up front, in
    # _main() — no need to reload it here.
    render_info = project.GetCurrentRenderFormatAndCodec()
    render_format = render_info.get('format', '').lower()  
    debug_print(f"Current render format: {render_format}")  
    
    
    is_exr = render_format == 'exr'
    debug_print(f"is_exr: {is_exr}")
    
    if counter_by_mark is None:
        counter_by_mark = {mark: i for i, mark in enumerate(sorted(markers))}

    ordered_marks = []
    raw_filenames = []

    # Computed once for the whole batch instead of per marker — see the
    # has_video_audio note on get_clip_at_marker().
    has_video, has_audio, _video_tracks, _audio_tracks = analyze_timeline_tracks(timeline, 0)

    for mark in sorted(markers):
        counter = counter_by_mark.get(mark, 0)
        clip_info = get_clip_at_marker(timeline, timeline.GetStartFrame() + mark, has_video_audio=(has_video, has_audio))
        if clip_info:
            clip_info['marker_frame'] = mark
            components = generate_naming_components(clip_info, counter, all_markers)
            
            filename = "_".join(filter(None, components.values()))

            ordered_marks.append(mark)
            raw_filenames.append(filename)

    # Guard against two markers generating the exact same filename (e.g. the
    # same Marker Name with no Auto Number/version component) — left as-is,
    # one render job would silently overwrite the other's output.
    unique_filenames = dup_fix(raw_filenames)
    if unique_filenames != raw_filenames:
        update_status("Some generated filenames were duplicates — added numbered suffixes to keep them unique")

    for mark, filename in zip(ordered_marks, unique_filenames):
        if is_exr:
            filename = filename + "."
            debug_print(f"EXR sequence detected, adding dot suffix. Filename: {filename}")

        filename_map[mark] = filename
            
    return filename_map

def preset_lst(proj):
    """
    Retrieves a list of render presets available in the project.

    Args:
        proj (Project): The project object containing the render presets.

    Returns:
        list: A list of render preset names, sorted alphabetically.
    """
    presets = []

    # Get all render presets
    all_presets = proj.GetRenderPresetList()

    # Sort presets alphabetically
    if all_presets:
        presets = sorted(all_presets)

    return presets


    
def export_stills(proj, tl, markers, all_markers, path, filenames):

    proj.SetCurrentTimeline(tl)
    print("Timeline set.")

    # The render preset is already loaded and validated once, up front, in
    # _main() — no need to reload it here.

    has_video, has_audio, video_tracks, audio_tracks = analyze_timeline_tracks(tl, 0)
    
    if not (has_video or has_audio):
        update_status("No media clips found to export")
        return
        
    media_type = "video" if has_video else "audio"
    update_status(f"Starting export of {len(markers)} {media_type} clips...")

    start_frame = tl.GetStartFrame()
    queued_clips = []
    queued_clip_ids = set()  # (timeline_start, timeline_end, track) for O(1) dedup lookups below
    counter = 0
    failed_markers = []  # frames where the render job could not be added, for the final summary

    initial_jobs = set(job['JobId'] for job in proj.GetRenderJobList() or [])
    folder_template = ""

    print(f"Processing {media_type} clips under markers...")

    selected_marker_mode = itm["marker_type"].CurrentText

    if selected_marker_mode in ("Single → Next Marker", "Single → Next Same Color"):
        # Range mode based on single markers:
        # IN = marker frame, OUT = next marker - 1
        # Last marker renders to end of timeline.
        selected_color = itm["marker_color"].CurrentText.split(" (")[0]

        if selected_marker_mode == "Single → Next Same Color" and selected_color != "All":
            # End range on the next marker with the same selected color (any type)
            all_marker_frames_sorted = sorted(
                frame for frame, marker in all_markers.items()
                if marker.get("color") == selected_color
            )
        else:
            # End range on the next marker of any color/type
            all_marker_frames_sorted = sorted(all_markers.keys())

        for mark in sorted(markers):
            marker_frame = start_frame + mark

            next_mark = None
            for f in all_marker_frames_sorted:
                if f > mark:
                    next_mark = f
                    break

            in_point = start_frame + mark
            if next_mark is not None:
                out_point = start_frame + next_mark - 1
            else:
                out_point = tl.GetEndFrame()

            validated_in, validated_out = validate_frame_range(in_point, out_point, tl)
            if validated_in is None or validated_out is None:
                failed_markers.append(marker_frame)
                skip_msg = f"Skipped range marker at frame {marker_frame}: invalid frame range"
                update_status(skip_msg)
                print(skip_msg)
                continue

            print(f"\nProcessing range marker {mark}: {validated_in} - {validated_out}")

            filename = filenames.get(mark, "")

            clip_info_for_folder = {
                'marker_frame': mark,
                'timeline_start': validated_in,
                'timeline_end': validated_out
            }
            target_dir = create_render_folder_path(path, filename, clip_info_for_folder, all_markers)

            render_settings = {
                "MarkIn": validated_in,
                "MarkOut": validated_out,
                "TargetDir": target_dir
            }

            if not itm["use_preset_naming"].Checked and filename:
                render_settings["CustomName"] = filename

            try:
                proj.SetRenderSettings(render_settings)
                if not proj.AddRenderJob():
                    raise RuntimeError("AddRenderJob returned false")

                queued_clips.append({
                    'timeline_start': validated_in,
                    'timeline_end': validated_out,
                    'job_id': None,
                    'target_dir': target_dir,
                    'media_type': media_type,
                    'marker_frame': mark,
                    'marker_type': 'single_to_next'
                })

                update_status(f"Added render job for range starting at frame {marker_frame}")
                print(f"Added render job for range starting at frame {marker_frame} to {target_dir}")
            except Exception as e:
                failed_markers.append(marker_frame)
                error_msg = f"Skipped marker at frame {marker_frame}: {str(e)}"
                update_status(error_msg)
                print(error_msg)

            counter += 1

    else:
        for mark in sorted(markers):
            marker_frame = start_frame + mark
            marker_data = all_markers.get(mark, {})
            marker_type = get_marker_type(marker_data)

            if marker_type == "duration":
                # Handle duration markers - use the same logic as Duration Markers script
                in_point = start_frame + mark
                out_point = start_frame + mark + marker_data['duration'] - 1

                # Validate frame range
                validated_in, validated_out = validate_frame_range(in_point, out_point, tl)
                if validated_in is None or validated_out is None:
                    failed_markers.append(marker_frame)
                    skip_msg = f"Skipped duration marker at frame {marker_frame}: invalid frame range"
                    update_status(skip_msg)
                    print(skip_msg)
                    continue

                print(f"\nProcessing duration marker {mark}: {validated_in} - {validated_out} (duration: {marker_data['duration']})")

                filename = filenames.get(mark, "")

                # Create folder path based on filename and settings
                clip_info_for_folder = {
                    'marker_frame': mark,
                    'timeline_start': validated_in,
                    'timeline_end': validated_out
                }
                target_dir = create_render_folder_path(path, filename, clip_info_for_folder, all_markers)

                render_settings = {
                    "MarkIn": validated_in,
                    "MarkOut": validated_out,
                    "TargetDir": target_dir
                }

                if not itm["use_preset_naming"].Checked and filename:
                    render_settings["CustomName"] = filename

                try:
                    proj.SetRenderSettings(render_settings)
                    if not proj.AddRenderJob():
                        raise RuntimeError("AddRenderJob returned false")

                    clip_info = {
                        'timeline_start': validated_in,
                        'timeline_end': validated_out,
                        'job_id': None,
                        'target_dir': target_dir,
                        'media_type': media_type,
                        'marker_frame': mark,
                        'marker_type': 'duration'
                    }
                    queued_clips.append(clip_info)

                    update_status(f"Added render job for duration marker at frame {marker_frame}")
                    print(f"Added render job for duration marker at frame {marker_frame} to {target_dir}")
                except Exception as e:
                    failed_markers.append(marker_frame)
                    error_msg = f"Skipped marker at frame {marker_frame}: {str(e)}"
                    update_status(error_msg)
                    print(error_msg)
            else:
                # Handle single markers (existing logic)
                clip_info = get_clip_at_marker(tl, marker_frame, has_video_audio=(has_video, has_audio))

                if clip_info:
                    print(f"\nProcessing single marker {mark}:")

                    # Add marker_frame to clip_info
                    clip_info['marker_frame'] = mark
                    print(f"Added marker_frame to clip_info: {mark}")

                    clip_id = (clip_info['timeline_start'], clip_info['timeline_end'], clip_info['track'])

                    if clip_id not in queued_clip_ids:
                        filename = filenames.get(mark, "")

                        # Create folder path based on filename and settings
                        target_dir = create_render_folder_path(path, filename, clip_info, all_markers)

                        render_settings = {
                            "MarkIn": clip_info['timeline_start'],
                            "MarkOut": clip_info['timeline_end'],
                            "TargetDir": target_dir
                        }

                        if not itm["use_preset_naming"].Checked and filename:
                            render_settings["CustomName"] = filename

                        try:
                            proj.SetRenderSettings(render_settings)
                            if not proj.AddRenderJob():
                                raise RuntimeError("AddRenderJob returned false")

                            clip_info.update({
                                'job_id': None,
                                'target_dir': target_dir,
                                'media_type': media_type
                            })
                            queued_clips.append(clip_info)
                            queued_clip_ids.add(clip_id)

                            update_status(f"Added render job for {media_type} clip at frame {marker_frame}")
                            print(f"Added render job for {media_type} clip at frame {marker_frame} to {target_dir}")
                        except Exception as e:
                            failed_markers.append(marker_frame)
                            error_msg = f"Skipped marker at frame {marker_frame}: {str(e)}"
                            update_status(error_msg)
                            print(error_msg)
                    else:
                        print("Clip already queued.")
                else:
                    failed_markers.append(marker_frame)
                    skip_msg = f"Skipped marker at frame {marker_frame}: no {media_type} clip found"
                    update_status(skip_msg)
                    print(skip_msg)

            counter += 1

    final_jobs = proj.GetRenderJobList() or []
    new_job_ids = set(job['JobId'] for job in final_jobs) - initial_jobs

    for clip_info in queued_clips:
        for job in final_jobs:
            if job['JobId'] in new_job_ids:
                if job['MarkIn'] == clip_info['timeline_start'] and job['MarkOut'] == clip_info['timeline_end']:
                    clip_info['job_id'] = job['JobId']
                    clip_info['render_name'] = job['OutputFilename']

    status_message = f"Render queue setup complete. Total {media_type} clips queued: {len(queued_clips)}"
    if failed_markers:
        frames_str = ", ".join(str(f) for f in failed_markers)
        status_message += f" — {len(failed_markers)} skipped (frames: {frames_str})"
    update_status(status_message)
    print(status_message)


################################################################################################
# MAIN EXECUTION
################################################################################################

def _main(ev):
    """
    Main execution function for rendering. Processes markers and adds clips to the render queue.

    Args:
        ev: The event object triggering this function.
    """
    # This tool always works with the same project/timeline that were active
    # in Resolve when it was launched (the "project"/"timeline" globals) —
    # never re-fetched mid-session, so filenames/naming (get_filenames,
    # get_component_value) and the actual render always agree on which
    # timeline they mean.
    if not timeline:
        update_status("No timeline selected")
        return

    # Validate the render preset up front — if it can't be loaded, abort
    # before touching markers/filenames rather than failing partway through
    # rendering.
    preset_name = itm["render_preset"].CurrentText
    if not preset_name:
        update_status("No render preset selected — pick one and try again")
        return
    if not project.LoadRenderPreset(preset_name):
        update_status(f"Render preset \"{preset_name}\" could not be loaded — pick a valid preset and try again")
        return

    markers, all_markers = get_markers(timeline)
    if not markers:
        # get_markers() already put a specific "no X Y markers found" message
        # in the status bar.
        return

    # Auto Number should reflect each marker's position among ALL markers
    # matching the current color/type filter — not just among whichever ones
    # happen to be checked for this particular render — so it stays stable
    # whether you render everything or just a checked subset.
    counter_by_mark = {mark: i for i, mark in enumerate(sorted(markers))}

    # If the user checked specific rows in the table, render only those
    # (that still match the current color/type filter); otherwise fall back
    # to the previous behavior of processing every filtered marker.
    if selected_frames:
        markers = [f for f in markers if f in selected_frames]
        if not markers:
            update_status("Checked marker(s) don't match the current color/type filter — nothing to render")
            return

    path = itm["export_path"].CurrentText
    filename_map = get_filenames(markers, all_markers, counter_by_mark)  
    export_stills(project, timeline, markers, all_markers, path, filename_map)

################################################################################################
# UI EVENT HANDLERS
################################################################################################
def load_naming_presets():
    """
    Loads naming presets into the dropdown list.
    """
    try:
        itm["naming_presets"].Clear()

        if not os.path.exists(PRESETS_FILE):
            _ensure_settings_dir()
            with open(PRESETS_FILE, 'w') as f:
                json.dump({}, f)
            itm["naming_presets"].AddItem("No presets available")
            return

        with open(PRESETS_FILE, 'r') as f:
            presets = json.load(f)
            
        if not presets:
            itm["naming_presets"].AddItem("No presets available")
            return
            
        
        preset_names = sorted(presets.keys())
        itm["naming_presets"].AddItems(preset_names)
        
    except Exception as e:
        print(f"Error loading naming presets: {str(e)}")
        itm["naming_presets"].AddItem("Error loading presets")
        update_status(f"Error loading presets: {str(e)}")

def save_naming_preset(ev=None):
    """
    Saves current naming settings as a preset.
    """
    try:
        preset_name = itm["preset_name_input"].Text.strip()
        if not preset_name:
            update_status("Preset name cannot be empty")
            return False
            
        
        settings = get_current_settings()
        
        
        presets = {}
        if os.path.exists(PRESETS_FILE):
            with open(PRESETS_FILE, 'r') as f:
                presets = json.load(f)
                
        
        if preset_name in presets:
            if not fu.AskQuestion("Overwrite Preset", 
                                f"Preset '{preset_name}' already exists. Overwrite?"):
                update_status("Preset save cancelled")
                return False
                
        
        presets[preset_name] = settings

        _ensure_settings_dir()
        with open(PRESETS_FILE, 'w') as f:
            json.dump(presets, f, indent=4)
            
        
        load_naming_presets()
        
        
        itm["naming_presets"].CurrentText = preset_name
        itm["preset_name_input"].Text = "" 
        
        update_status(f"Preset '{preset_name}' saved successfully")
        return True
        
    except Exception as e:
        update_status(f"Error saving preset: {str(e)}")
        print(f"Error saving preset: {str(e)}")
        return False

def load_naming_preset(ev=None):

    try:
        preset_name = itm["naming_presets"].CurrentText
        if not preset_name or preset_name == "No presets available":
            update_status("No preset selected")
            return False
            
        
        with open(PRESETS_FILE, 'r') as f:
            presets = json.load(f)
            
        if preset_name not in presets:
            update_status(f"Preset '{preset_name}' not found")
            return False
            
        
        settings = presets[preset_name]
        apply_settings_to_ui(settings)
        update_naming_preview()
        
        update_status(f"Preset '{preset_name}' loaded successfully")
        return True
        
    except Exception as e:
        update_status(f"Error loading preset: {str(e)}")
        print(f"Error loading preset: {str(e)}")
        return False

def delete_naming_preset(ev=None):

    try:
        preset_name = itm["naming_presets"].CurrentText
        if not preset_name or preset_name == "No presets available":
            update_status("No preset selected")
            return False
           
            
        
        with open(PRESETS_FILE, 'r') as f:
            presets = json.load(f)
            
        if preset_name not in presets:
            update_status(f"Preset '{preset_name}' not found")
            return False
            
        
        del presets[preset_name]

        _ensure_settings_dir()
        with open(PRESETS_FILE, 'w') as f:
            json.dump(presets, f, indent=4)
            
        
        load_naming_presets()
        
        update_status(f"Preset '{preset_name}' deleted successfully")
        return True
        
    except Exception as e:
        update_status(f"Error deleting preset: {str(e)}")
        print(f"Error deleting preset: {str(e)}")
        return False

        
def apply_settings_to_ui(settings):
    """
    Applies the given settings to the UI
    
    Args:
        settings (dict): The settings to apply
    """
    # Component 1
    if "component1" in settings:
        itm["component1_enabled"].Checked = settings["component1"]["enabled"]
        itm["component1_source"].CurrentText = settings["component1"]["source"]
        itm["component1_custom"].Text = settings["component1"]["custom"]
        toggle_custom_field("component1_source", "component1_custom")
        
    # Component 2
    if "component2" in settings:
        itm["component2_enabled"].Checked = settings["component2"]["enabled"]
        itm["component2_source"].CurrentText = settings["component2"]["source"]
        itm["component2_custom"].Text = settings["component2"]["custom"]
        toggle_custom_field("component2_source", "component2_custom")
        
    # Component 3
    if "component3" in settings:
        itm["component3_enabled"].Checked = settings["component3"]["enabled"]
        itm["component3_source"].CurrentText = settings["component3"]["source"]
        itm["component3_custom"].Text = settings["component3"]["custom"]
        toggle_custom_field("component3_source", "component3_custom")
        
    # ShotID
    if "shotID" in settings:
        itm["shotID_enabled"].Checked = settings["shotID"]["enabled"]
        itm["shotID_source"].CurrentText = settings["shotID"]["source"]
        itm["shotID_start"].Value = settings["shotID"]["start"]
        itm["shotID_step"].Value = settings["shotID"]["step"]
        itm["shotID_padding"].Value = settings["shotID"]["padding"]
        
    # Task
    if "task" in settings:
        itm["task_enabled"].Checked = settings["task"]["enabled"]
        itm["task_source"].CurrentText = settings["task"]["source"]
        itm["task_custom"].Text = settings["task"]["custom"]
        toggle_custom_field("task_source", "task_custom")
        
    # Version
    if "version" in settings:
        itm["version_enabled"].Checked = settings["version"]["enabled"]
        itm["version_prefix"].Text = settings["version"]["prefix"]
        itm["version_start"].Value = settings["version"]["start"]
        itm["version_padding"].Value = settings["version"]["padding"]
def _close(ev):
    """
    Handles the window close event. Exits the UI event loop.

    Args:
        ev: The event object triggering this function.
    """
    disp.ExitLoop()



def _file_browser(ev):
    location = fu.RequestDir()
    if location:
        paths = update_render_paths(location)
        itm["export_path"].Clear()
        itm["export_path"].AddItems(paths)
        itm["export_path"].CurrentText = location
        # update_export_button_state()

last_preview_update = 0
preview_cooldown = 0.5 


is_updating_table = False
is_initializing = False

# Relative frame ids (as used by AddMarker/DeleteMarkerAtFrame) of markers the
# user has checked in the table, for restricting render/delete to a subset.
selected_frames = set()

def initialize_naming_settings():
    """
    Initializes the naming settings comboboxes with predefined options.
    """
    naming_sources = {
        "component1_source": ["ProjectName", "TimelineName", "TimelineFPS", "TimelineResolution", "RenderFormat", "RenderCodec", "RenderFormatCodec", "MarkerName", "MarkerNote", "Reel Name", "SourceName", "ClipName", "Custom"],
        "component2_source": ["ProjectName", "TimelineName", "TimelineFPS", "TimelineResolution", "RenderFormat", "RenderCodec", "RenderFormatCodec", "MarkerName", "MarkerNote", "Reel Name", "SourceName", "ClipName", "Custom"],
        "component3_source": ["ProjectName", "TimelineName", "TimelineFPS", "TimelineResolution", "RenderFormat", "RenderCodec", "RenderFormatCodec", "MarkerName", "MarkerNote", "Reel Name", "SourceName", "ClipName", "Custom"],
        "shotID_source": ["Auto Number", "Reel Name", "SourceName", "ClipName", "MarkerName", "MarkerNote"],
        "task_source": ["comp", "anim", "roto", "match", "paint", "Custom"]
    }

    for source_id, sources in naming_sources.items():
        itm[source_id].Clear()
        itm[source_id].AddItems(sources)
        
    # Load existing presets
    load_naming_presets()

load_naming_presets()
    
def toggle_custom_field(source_id, custom_id):
    """
    Enables or disables a custom field based on the selected source.

    Args:
        source_id (str): The ID of the source combobox.
        custom_id (str): The ID of the custom field to toggle.
    """
    is_custom = itm[source_id].CurrentText == "Custom"
    itm[custom_id].Enabled = is_custom
    update_naming_preview()


def setup_custom_field_handlers():
    """
    Sets up event handlers for all custom fields to toggle their enabled state.
    """
    custom_mappings = [
        ("component1_source", "component1_custom"),
        ("component2_source", "component2_custom"),
        ("component3_source", "component3_custom"),
        ("task_source", "task_custom")
    ]

    for source_id, custom_id in custom_mappings:
        # Set initial state
        toggle_custom_field(source_id, custom_id)

        # Add event handler for source change
        window.On[source_id].CurrentIndexChanged = lambda ev, s=source_id, c=custom_id: (
            toggle_custom_field(s, c),
            update_naming_preview()
        )

def bind_naming_preview_handlers():
    """
    Binds event handlers to update the naming preview when settings change.
    """
    # Checkboxes
    checkboxes = [
        "component1_enabled", "component2_enabled", "component3_enabled",
        "shotID_enabled", "task_enabled", "version_enabled"
    ]
    for cb in checkboxes:
        window.On[cb].Clicked = lambda _: update_naming_preview()

    # ComboBoxes - используем CurrentIndexChanged вместо Clicked
    comboboxes = [
        "component1_source", "component2_source", "component3_source",
        "shotID_source", "task_source"
    ]
    for cb in comboboxes:
        window.On[cb].CurrentIndexChanged = lambda _: update_naming_preview()

    # Text fields and spinboxes
    window.On.version_prefix.TextChanged = lambda _: update_naming_preview()
    window.On.version_start.ValueChanged = lambda _: update_naming_preview()
    window.On.version_padding.ValueChanged = lambda _: update_naming_preview()
    window.On.shotID_start.ValueChanged = lambda _: update_naming_preview()
    window.On.shotID_step.ValueChanged = lambda _: update_naming_preview()
    window.On.shotID_padding.ValueChanged = lambda _: update_naming_preview()

    # Custom fields
    custom_fields = [
        "component1_custom", "component2_custom", "component3_custom", "task_custom"
    ]
    for field in custom_fields:
        window.On[field].TextChanged = lambda _: update_naming_preview()

    # Preset naming checkbox
    window.On.use_preset_naming.Clicked = lambda _: update_naming_preview()
    
    # Preset buttons
    window.On.save_preset.Clicked = save_naming_preset
    window.On.load_preset.Clicked = load_naming_preset
    window.On.delete_preset.Clicked = delete_naming_preset

def toggle_naming_settings(ev):
    """
    Enables or disables naming settings based on render preset naming checkbox state
    """
    is_preset_naming = itm["use_preset_naming"].Checked
    
    # List of naming settings UI elements to disable
    naming_elements = [
        "component1_enabled", "component1_source", "component1_custom",
        "component2_enabled", "component2_source", "component2_custom",
        "component3_enabled", "component3_source", "component3_custom",
        "shotID_enabled", "shotID_source", "shotID_start", "shotID_step", "shotID_padding",
        "task_enabled", "task_source", "task_custom", 
        "version_enabled", "version_prefix", "version_start", "version_padding"
    ]
    
    for element_id in naming_elements:
        itm[element_id].Enabled = not is_preset_naming
    label_style = "font-weight: bold; color: #777; font-size: 14px;" if is_preset_naming else "font-weight: bold; color: #FFFFFF; font-size: 16px;"
    window.Find("Custom Naming Settings").SetStyleSheet(label_style)   
    update_naming_preview()


# Call this during final initialization
bind_naming_preview_handlers()
# Call this during initialization
setup_custom_field_handlers()
# Call this during initialization
initialize_naming_settings()

def populate_markers_table(ev=None):
    """
    Populates the markers table with markers from the current timeline.
    """
    table = itm["markers_table"]
    table.SetHeaderLabels(["", "Timecode", "Color", "Marker Name", "Source Name", "Clip Name", "Note", "Reel Name"])
    
    global is_updating_table
    debug_print(f"populate_markers_table called, event: {ev}, is_updating_table: {is_updating_table}")
    if is_updating_table:
        debug_print("Skipping due to is_updating_table")
        return

    try:
        is_updating_table = True
        # Always the timeline this session is locked to (the "timeline"
        # global) — never re-fetched, so this always agrees with Export.
        current_timeline = timeline
        if not current_timeline:
            return

        markers = current_timeline.GetMarkers()
        if not markers:
            update_status("No markers found on timeline")
            return
            
        has_video, has_audio, video_tracks, audio_tracks = analyze_timeline_tracks(current_timeline, 0)
        
        if not (has_video or has_audio):
            update_status("No media clips found on timeline")
            return
            
        if has_video:
            tracks_info = ", ".join([f"Track {t['track']}: {t['count']} clips" for t in video_tracks])
            update_status(f"Found {len(markers)} markers. Video tracks: {tracks_info}")
        else:
            tracks_info = ", ".join([f"Track {t['track']}: {t['count']} clips" for t in audio_tracks])
            update_status(f"No video clips found. Processing {len(markers)} markers for audio. Audio tracks: {tracks_info}")

        table = itm["markers_table"]
        if not table:
            return

        # Clear the table before populating
        table.Clear()

        selected_color = itm["marker_color"].CurrentText.split(" (")[0]
        fps = float(current_timeline.GetSetting('timelineFrameRate'))
        smpte.fps = fps  # keep the timecode converter in sync with the actual timeline
        start_frame = current_timeline.GetStartFrame()

        # Prepare data for the table
        table_items = []
        selected_marker_mode = itm["marker_type"].CurrentText

        for frame, marker in sorted(markers.items()):
            if selected_color != "All" and marker.get("color", "") != selected_color:
                continue

            # Check marker type filter
            marker_type = get_marker_type(marker)
            selected_type = "duration" if itm["marker_type"].CurrentText == "Duration" else "single"
            if marker_type != selected_type:
                continue

            timeline_frame = start_frame + frame
            clip_info = get_clip_at_marker(current_timeline, timeline_frame, has_video_audio=(has_video, has_audio))

            # For duration markers, we don't need clip_info to be valid
            # For range modes, we also allow markers without clip_info
            if marker_type == "duration" or selected_marker_mode in ("Single → Next Marker", "Single → Next Same Color") or clip_info:
                source_name = ""
                clip_name = ""
                reel_name = ""
                
                if clip_info:
                    # Source Name - always from MediaPoolItem (original file name)
                    source_name = clip_info['media_pool_item'].GetName()
                    
                    # Clip Name - from TimelineItem (what's displayed on timeline)
                    # Note: TimelineItem.GetName() behavior depends on "Show file names" setting:
                    # - If "Show file names" is ON: returns source file name
                    # - If "Show file names" is OFF: returns custom clip name (if set) or source file name
                    # Unfortunately, there's no direct API way to get the custom clip name independently
                    if clip_info.get('clip'):
                        timeline_item_name = clip_info['clip'].GetName() or ""
                        clip_name = timeline_item_name
                        
                        # If names are the same, add a note to help user understand
                        # (they might be the same because "Show file names" is ON, 
                        #  or because user set clip name to match source name)
                        if clip_name == source_name and clip_name:
                            # Keep both values visible - user can see they match
                            pass
                    
                    # Get Reel Name from media pool item
                    try:
                        reel_name = clip_info['media_pool_item'].GetClipProperty('Reel Name')
                    except Exception as e:
                        print(f"Error getting Reel Name: {str(e)}")
                else:
                    # For duration/range markers without clip info, use marker info
                    source_name = "Duration Range" if marker_type == "duration" else "Range Start"
                    clip_name = ""
                    reel_name = ""

                total_frames = int(timeline_frame)
                timecode = smpte.gettc(total_frames)

                table_items.append({
                    'frame': frame,  # relative frame id, as used by AddMarker/DeleteMarkerAtFrame
                    'timecode': timecode,
                    'color': marker.get("color", ""),
                    'name': marker.get("name", ""),
                    'source': source_name,
                    'clip_name': clip_name,
                    'note': marker.get("note", ""),
                    'reel_name': reel_name,  # Add Reel Name to the table
                    'type': marker_type
                })

        # Add items to the table
        for item_data in table_items:
            item = table.NewItem()
            # Checkbox column: lets the user pick specific markers for
            # rendering (see _main) or for deletion (see delete_checked_markers).
            item.Flags = {"ItemIsSelectable": True, "ItemIsEnabled": True, "ItemIsUserCheckable": True}
            item.CheckState[0] = "Checked" if item_data['frame'] in selected_frames else "Unchecked"
            item.SetData(0, "UserRole", str(item_data['frame']))
            item.Text[1] = item_data['timecode']
            item.Text[2] = item_data['color']
            item.Text[3] = item_data['name']
            item.Text[4] = item_data['source']
            item.Text[5] = item_data['clip_name']
            item.Text[6] = item_data['note']
            item.Text[7] = item_data['reel_name']  # Add Reel Name to the table
            table.AddTopLevelItem(item)
        table.SortByColumn(1, "AscendingOrder")

        # Drop any remembered checked frames that no longer exist on the
        # timeline (e.g. deleted from the Edit page) or are no longer shown
        # under the current color/type filter, so the count stays accurate.
        visible_frames = {item_data['frame'] for item_data in table_items}
        selected_frames.intersection_update(visible_frames)
    except Exception as e:
        update_status(f"Error: {str(e)}")
        print(f"Error in populate_markers_table: {str(e)}")
    finally:
        is_updating_table = False
        debug_print("populate_markers_table finished")

# Table column indices (kept in one place since several handlers below need them)
COL_CHECK = 0
COL_TIMECODE = 1
COL_COLOR = 2
COL_NAME = 3
COL_SOURCE = 4
COL_CLIP = 5
COL_NOTE = 6
COL_REEL = 7


################################################################################################
# MARKER EDITING (rename / re-color / re-note / delete via the table)
################################################################################################
#
# The Resolve API has no "update marker" call — the only way to change a
# marker's color/name/note is to delete it and re-add it at the same frame
# with the new values (duration and customData are carried over as-is).

def _apply_marker_edit(tl, frame, marker, **overrides):
    """
    Re-creates a marker at `frame` with one or more fields overridden.

    Args:
        tl: The timeline the marker belongs to.
        frame (int): Relative frame id (the key from GetMarkers()).
        marker (dict): The marker's current data, as returned by GetMarkers().
        **overrides: Any of color/name/note to change.

    Returns:
        bool: True if the marker was successfully re-added.
    """
    color = overrides.get("color", marker.get("color", "Blue"))
    name = overrides.get("name", marker.get("name", ""))
    note = overrides.get("note", marker.get("note", ""))
    duration = marker.get("duration", 1) or 1
    custom_data = marker.get("customData", "")

    if not tl.DeleteMarkerAtFrame(frame):
        update_status(f"Failed to update marker at frame {frame}")
        return False

    if not tl.AddMarker(frame, color, name, note, duration, custom_data):
        update_status(f"Failed to re-add marker at frame {frame} after edit")
        # Try to restore the original marker so we don't lose it entirely
        tl.AddMarker(frame, marker.get("color", "Blue"), marker.get("name", ""),
                     marker.get("note", ""), duration, custom_data)
        return False

    return True


# --- Small reusable modal dialogs (built once, reused on every call) --------

_dialog_cache = {}


def _get_text_dialog():
    """Lazily builds (once) the small modal dialog used to edit Name/Note."""
    if "text" not in _dialog_cache:
        dlg = disp.AddWindow(
            {
                "ID": "MTR_TextEditDialog",
                "WindowTitle": "Edit",
                "Geometry": [300, 300, 420, 120],
                "WindowFlags": {"Window": True, "WindowStaysOnTopHint": True},
            },
            ui.VGroup({"Spacing": 8}, [
                ui.Label({"ID": "text_edit_label", "Text": ""}),
                ui.LineEdit({"ID": "text_edit_value"}),
                ui.HGroup({"Spacing": 6}, [
                    ui.Button({"ID": "text_edit_ok", "Text": "OK"}),
                    ui.Button({"ID": "text_edit_cancel", "Text": "Cancel"}),
                ]),
            ])
        )
        _dialog_cache["text"] = dlg
        _dialog_cache["text_itm"] = dlg.GetItems()
    return _dialog_cache["text"], _dialog_cache["text_itm"]


def _prompt_text(title, label, initial_text=""):
    """Shows the text-edit dialog and returns the new text, or None if cancelled."""
    dlg, ditm = _get_text_dialog()
    dlg.WindowTitle = title
    ditm["text_edit_label"].Text = label
    ditm["text_edit_value"].Text = initial_text

    result = {"value": None}

    def _accept(ev):
        result["value"] = ditm["text_edit_value"].Text
        disp.ExitLoop()

    def _reject(ev):
        result["value"] = None
        disp.ExitLoop()

    dlg.On.text_edit_ok.Clicked = _accept
    dlg.On.text_edit_cancel.Clicked = _reject
    dlg.On.MTR_TextEditDialog.Close = _reject

    dlg.Show()
    disp.RunLoop()
    dlg.Hide()
    return result["value"]


def _get_color_dialog():
    """Lazily builds (once) the small modal dialog used to edit the marker Color."""
    if "color" not in _dialog_cache:
        dlg = disp.AddWindow(
            {
                "ID": "MTR_ColorEditDialog",
                "WindowTitle": "Edit Marker Color",
                "Geometry": [300, 300, 320, 110],
                "WindowFlags": {"Window": True, "WindowStaysOnTopHint": True},
            },
            ui.VGroup({"Spacing": 8}, [
                ui.Label({"Text": "New marker color:"}),
                ui.ComboBox({"ID": "color_edit_value"}),
                ui.HGroup({"Spacing": 6}, [
                    ui.Button({"ID": "color_edit_ok", "Text": "OK"}),
                    ui.Button({"ID": "color_edit_cancel", "Text": "Cancel"}),
                ]),
            ])
        )
        _dialog_cache["color"] = dlg
        _dialog_cache["color_itm"] = dlg.GetItems()
        # "Items" set at creation time isn't reliably picked up by this UI
        # framework (same reason marker_type/render_preset etc. are populated
        # via AddItems() after the fact elsewhere in this script) — populate
        # explicitly instead.
        _dialog_cache["color_itm"]["color_edit_value"].AddItems(color_lst[1:])  # skip "All"
    return _dialog_cache["color"], _dialog_cache["color_itm"]


def _prompt_color(current_color):
    """Shows the color-edit dialog and returns the chosen color, or None if cancelled."""
    dlg, ditm = _get_color_dialog()
    if current_color in color_lst[1:]:
        ditm["color_edit_value"].CurrentText = current_color

    result = {"value": None}

    def _accept(ev):
        result["value"] = ditm["color_edit_value"].CurrentText
        disp.ExitLoop()

    def _reject(ev):
        result["value"] = None
        disp.ExitLoop()

    dlg.On.color_edit_ok.Clicked = _accept
    dlg.On.color_edit_cancel.Clicked = _reject
    dlg.On.MTR_ColorEditDialog.Close = _reject

    dlg.Show()
    disp.RunLoop()
    dlg.Hide()
    return result["value"]


def _get_confirm_dialog():
    """Lazily builds (once) a generic Yes/No confirmation dialog."""
    if "confirm" not in _dialog_cache:
        dlg = disp.AddWindow(
            {
                "ID": "MTR_ConfirmDialog",
                "WindowTitle": "Confirm",
                "Geometry": [300, 300, 380, 120],
                "WindowFlags": {"Window": True, "WindowStaysOnTopHint": True},
            },
            ui.VGroup({"Spacing": 10}, [
                ui.Label({"ID": "confirm_label", "Text": "", "WordWrap": True}),
                ui.HGroup({"Spacing": 6}, [
                    ui.Button({"ID": "confirm_yes", "Text": "Yes"}),
                    ui.Button({"ID": "confirm_no", "Text": "No"}),
                ]),
            ])
        )
        _dialog_cache["confirm"] = dlg
        _dialog_cache["confirm_itm"] = dlg.GetItems()
    return _dialog_cache["confirm"], _dialog_cache["confirm_itm"]


def _confirm(title, message):
    dlg, ditm = _get_confirm_dialog()
    dlg.WindowTitle = title
    ditm["confirm_label"].Text = message

    result = {"value": False}

    def _yes(ev):
        result["value"] = True
        disp.ExitLoop()

    def _no(ev):
        result["value"] = False
        disp.ExitLoop()

    dlg.On.confirm_yes.Clicked = _yes
    dlg.On.confirm_no.Clicked = _no
    dlg.On.MTR_ConfirmDialog.Close = _no

    dlg.Show()
    disp.RunLoop()
    dlg.Hide()
    return result["value"]


def refresh_marker_color_filter():
    """
    Rebuilds the "Marker Color" filter dropdown from the timeline's current
    markers (colors + counts), keeping the current selection if that color
    still exists. Needed after any edit/delete that can change which colors
    are in use or how many markers of each color there are — the dropdown
    is otherwise only built once at startup.
    """
    current_timeline = timeline
    previous_color = itm["marker_color"].CurrentText.split(" (")[0]
    used_colors_with_counts = get_used_marker_colors(current_timeline)

    itm["marker_color"].Clear()
    itm["marker_color"].AddItems(used_colors_with_counts)

    for entry in used_colors_with_counts:
        if entry.split(" (")[0] == previous_color:
            itm["marker_color"].CurrentText = entry
            break
    else:
        itm["marker_color"].CurrentText = used_colors_with_counts[0]


def on_marker_double_clicked(ev):
    """
    Double-click behavior in the markers table:
    - Timecode column: jumps the playhead to that timecode (original behavior).
    - Color / Marker Name / Note columns: opens a small dialog to edit the
      marker in place (the timeline marker is deleted and re-added with the
      new value, since Resolve has no direct "update marker" call).
    """
    try:
        item = ev["item"]
        column = ev.get("column", COL_TIMECODE)

        if column == COL_TIMECODE:
            timecode = item.Text[COL_TIMECODE]
            current_timeline = timeline
            if current_timeline:
                current_timeline.SetCurrentTimecode(timecode)
                print(f"Moved playhead to timecode {timecode}")
            return

        if column not in (COL_COLOR, COL_NAME, COL_NOTE):
            return

        frame_data = item.GetData(0, "UserRole")
        if not frame_data:
            return
        frame = int(frame_data)

        current_timeline = timeline
        if not current_timeline:
            update_status("No timeline")
            return

        markers = current_timeline.GetMarkers()
        marker = markers.get(frame)
        if marker is None:
            update_status("That marker no longer exists — refreshing the list")
            populate_markers_table()
            return

        if column == COL_COLOR:
            new_value = _prompt_color(marker.get("color", "Blue"))
            if new_value is None or new_value == marker.get("color", ""):
                return
            if _apply_marker_edit(current_timeline, frame, marker, color=new_value):
                update_status(f"Marker color changed to {new_value}")
                refresh_marker_color_filter()

        elif column == COL_NAME:
            new_value = _prompt_text("Edit Marker Name", "Marker name:", marker.get("name", ""))
            if new_value is None or new_value == marker.get("name", ""):
                return
            if _apply_marker_edit(current_timeline, frame, marker, name=new_value):
                update_status(f"Marker renamed to \"{new_value}\"")

        elif column == COL_NOTE:
            new_value = _prompt_text("Edit Marker Note", "Note:", marker.get("note", ""))
            if new_value is None or new_value == marker.get("note", ""):
                return
            if _apply_marker_edit(current_timeline, frame, marker, note=new_value):
                update_status("Marker note updated")

        populate_markers_table()

    except Exception as e:
        update_status(f"Error editing marker: {str(e)}")
        print(f"Error in double click handler: {str(e)}")
        import traceback
        traceback.print_exc()


def on_marker_item_changed(ev):
    """
    Tracks checkbox toggles in the markers table (column 0) so a subset of
    markers can be chosen for rendering (see _main) or deletion (see
    delete_checked_markers), without rebuilding the whole table — which would
    wipe out every other row's check state.
    """
    global is_updating_table
    if is_updating_table:
        return
    item = ev.get("item")
    column = ev.get("column")
    if item is None or column != COL_CHECK:
        return
    try:
        frame_data = item.GetData(0, "UserRole")
        if not frame_data:
            return
        frame = int(frame_data)
        if item.CheckState[COL_CHECK] == "Checked":
            selected_frames.add(frame)
        else:
            selected_frames.discard(frame)
        if selected_frames:
            update_status(f"{len(selected_frames)} marker(s) checked")
    except Exception as e:
        update_status(f"Error updating checkbox: {str(e)}")
        print(f"Error in checkbox handler: {str(e)}")


def delete_checked_markers(ev):
    """Deletes every marker currently checked in the table, after confirmation."""
    current_timeline = timeline
    if not current_timeline:
        update_status("No timeline")
        return
    if not selected_frames:
        update_status("No markers checked — check a box in the table first")
        return

    count = len(selected_frames)
    if not _confirm("Delete Markers", f"Delete {count} checked marker(s) from the timeline? This cannot be undone."):
        return

    deleted = 0
    for frame in sorted(selected_frames):
        if current_timeline.DeleteMarkerAtFrame(frame):
            deleted += 1
    selected_frames.clear()
    update_status(f"Deleted {deleted} of {count} checked marker(s)")
    refresh_marker_color_filter()
    populate_markers_table()


def clear_marker_selection(ev):
    """Unchecks every marker without deleting anything."""
    selected_frames.clear()
    update_status("Marker checks cleared")
    populate_markers_table()

################################################################################################
# FILENAME MANAGEMENT
################################################################################################
def generate_naming_components(clip_info, counter, markers):
    """
    Generates naming components based on current settings
    
    Args:
        clip_info (dict): Information about the clip
        counter (int): Counter for the current clip
        markers (dict): Dictionary with marker information
        
    Returns:
        dict: Dictionary with naming components
    """
    current_settings = get_current_settings()
    components = {}
    
    # Get marker data
    marker_frame = clip_info.get('marker_frame')
    example_data = {}
    if marker_frame is not None and marker_frame in markers:
        marker_data = markers[marker_frame]
        example_data = {
            'marker_name': marker_data.get('name', ''),
            'marker_note': marker_data.get('note', ''),
            'reel_name': marker_data.get('reel_name', '')
        }
    
    # Process each component
    components["component1"] = get_component_value(current_settings["component1"], clip_info, example_data, "comp1", counter)
    components["component2"] = get_component_value(current_settings["component2"], clip_info, example_data, "comp2", counter)
    components["component3"] = get_component_value(current_settings["component3"], clip_info, example_data, "comp3", counter)
    
    # ShotID
    if current_settings["shotID"]["enabled"]:
        shot_value = get_component_value(current_settings["shotID"], clip_info, example_data, "SHOT010", counter)
        if shot_value:
            components["shotID"] = shot_value
    
    # Task
    if current_settings["task"]["enabled"]:
        if current_settings["task"]["source"] == "Custom":
            components["task"] = current_settings["task"]["custom"] or "task"
        else:
            components["task"] = current_settings["task"]["source"]
    
    # Version
    if current_settings["version"]["enabled"]:
        prefix = current_settings["version"]["prefix"] or "v"
        version_pad = current_settings["version"]["padding"]
        version_num = str(current_settings["version"]["start"]).zfill(version_pad)
        components["version"] = f"{prefix}{version_num}"
    
    # Remove None values
    return {k: v for k, v in components.items() if v is not None}

def dup_fix(names):
    """
    Adds numbered suffixes to duplicate names to ensure uniqueness.

    Args:
        names (list): A list of names to check for duplicates.

    Returns:
        list: A list of unique names with suffixes added where necessary.
    """
    seen = {}
    result = []

    for i, name in enumerate(names):
        if name in seen:
            counter = seen[name] + 1
            seen[name] = counter
            result.append(f"{name}_{counter}")
        else:
            seen[name] = 1
            result.append(name)

    return result

################################################################################################
# UI INITIALIZATION
################################################################################################

# Initialize UI state
is_initializing = True
try:
    # Populate marker colors, render presets, and timelines
    used_colors_with_counts = get_used_marker_colors(timeline)
    itm['marker_color'].AddItems(used_colors_with_counts)
    itm["render_preset"].AddItems(preset_lst(project))
    current_tl_name = get_session_timeline_name()
    itm["tl_preset_label"].Text = current_tl_name or "— none —"
    # Load saved render paths
    itm["export_path"].AddItems(load_render_paths())
    
    # Populate video tracks
    video_track_count = timeline.GetTrackCount("video") if timeline else 0
    video_track_options = ["Default (Topmost)"] + [f"Video Track {i+1}" for i in range(video_track_count)]
    itm["video_track"].AddItems(video_track_options)
    
    # Initialize marker type combobox
    itm["marker_type"].AddItems(["Single", "Duration", "Single → Next Marker", "Single → Next Same Color"])
    itm["marker_type"].CurrentText = "Single"

    if not timeline:
        # No timeline in the project (e.g. brand new/empty project) — let the
        # user see the UI, just keep it inert until a timeline exists.
        update_status("No timeline found in this project. Open or create a timeline, then reopen this tool.")
        itm["Export"].Enabled = False
    else:
        # Populate markers table
        populate_markers_table()
finally:
    is_initializing = False

# Restore the marker color change handler
window.On.marker_color.CurrentIndexChanged = populate_markers_table
window.On["video_track"].CurrentIndexChanged = populate_markers_table
window.On.marker_type.CurrentIndexChanged = populate_markers_table

# Set up event handlers
window.On["export_path"].TextChanged = update_export_button_state
window.On.Export.Clicked = _main
window.On.export_location.Clicked = _file_browser
window.On.MTRWin.Close = _close
window.On["markers_table"].ItemDoubleClicked = on_marker_double_clicked
window.On["markers_table"].ItemChanged = on_marker_item_changed
window.On.delete_markers_btn.Clicked = delete_checked_markers
window.On.clear_selection_btn.Clicked = clear_marker_selection
window.On.use_preset_naming.Clicked = toggle_naming_settings
# Button handlers
window.On.save_preset.Clicked = save_naming_preset
window.On.load_preset.Clicked = load_naming_preset
window.On.delete_preset.Clicked = delete_naming_preset

# Initialize naming preview
update_naming_preview()

# Initial state setup
toggle_naming_settings(None)

# Show window and start event loop
window.Show()
disp.RunLoop()
window.Hide()
