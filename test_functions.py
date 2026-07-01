import importlib.util
import os


def load_module_from_path(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_constants_and_presets():
    gui_mod = load_module_from_path(
        "gui_module",
        os.path.join(os.path.dirname(__file__), "01_GUI_cogtiff_4band_to_3band.py"),
    )

    assert os.path.basename(gui_mod.RUNNER_SCRIPT) == "_osgeo_runner.py"
    assert isinstance(gui_mod.PRESETS, list) and len(gui_mod.PRESETS) >= 1
    assert isinstance(gui_mod.CONFIG_FILE, str) and gui_mod.CONFIG_FILE.endswith("_cogtiff_config.json")


def test_detect_python_home_returns_string():
    gui_mod = load_module_from_path(
        "gui_module",
        os.path.join(os.path.dirname(__file__), "01_GUI_cogtiff_4band_to_3band.py"),
    )

    candidate = os.path.join("C:", "OSGeo4W", "bin", "python3.exe")
    res = gui_mod._detect_python_home(candidate)
    assert isinstance(res, str)


def test_app_class_exists():
    gui_mod = load_module_from_path(
        "gui_module",
        os.path.join(os.path.dirname(__file__), "01_GUI_cogtiff_4band_to_3band.py"),
    )
    assert callable(gui_mod.BandKonverterApp)


def test_nodata_presets_for_mosaic_tab():
    gui_mod = load_module_from_path(
        "gui_module",
        os.path.join(os.path.dirname(__file__), "01_GUI_cogtiff_4band_to_3band.py"),
    )
    assert set(gui_mod.NODATA_OPTIONS.keys()) == {"8bit", "16bit"}
    assert "0 0 0" in gui_mod.NODATA_OPTIONS["8bit"]
    assert "0 0 0 0" in gui_mod.NODATA_OPTIONS["16bit"]


def test_mosaic_action_available():
    runner_mod = load_module_from_path(
        "runner_module",
        os.path.join(os.path.dirname(__file__), "_osgeo_runner.py"),
    )
    assert callable(runner_mod._mosaic)
