import os


def test_constants_and_presets():
    from GUI_cogtiff_4band_to_3band import RUNNER_SCRIPT, PRESETS, CONFIG_FILE

    assert os.path.basename(RUNNER_SCRIPT) == "_osgeo_runner.py"
    assert isinstance(PRESETS, list) and len(PRESETS) >= 1
    assert isinstance(CONFIG_FILE, str) and CONFIG_FILE.endswith("_cogtiff_config.json")


def test_detect_python_home_returns_string():
    from GUI_cogtiff_4band_to_3band import _detect_python_home

    # Provide a plausible python executable path; function should return a string (root or apps path)
    candidate = os.path.join("C:", "OSGeo4W", "bin", "python3.exe")
    res = _detect_python_home(candidate)
    assert isinstance(res, str)


def test_app_class_exists():
    from GUI_cogtiff_4band_to_3band import BandKonverterApp
    assert callable(BandKonverterApp)
