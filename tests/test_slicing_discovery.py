"""Finding Bambu Studio and its profiles (bambu_studio_ai.slicing.discovery).

Each test describes a machine with ``Host`` (OS, home folder, environment) and builds
the folders it needs under tmp_path, so the result doesn't depend on what is installed.
"""

import json
from pathlib import Path, PureWindowsPath

from bambu_studio_ai.slicing.discovery import (
    CLI_ENV,
    PROFILES_ENV,
    Host,
    bundle_version,
    cli_candidates,
    find_cli,
    find_profiles_dir,
    profile_candidates,
)


def make_bundle(root, version):
    (root / "BBL").mkdir(parents=True)
    (root / "BBL.json").write_text(json.dumps({"version": version}), encoding="utf-8")
    return root


def test_macos_looks_in_the_app_bundle_first(tmp_path):
    host = Host(system="Darwin", home=tmp_path)
    (first,) = cli_candidates(host)[0]
    assert Path(first) == Path("/Applications/BambuStudio.app/Contents/MacOS/BambuStudio")
    profiles = profile_candidates(host)
    assert profiles[0] == Path("/Applications/BambuStudio.app/Contents/Resources/profiles")
    assert tmp_path / "Library" / "Application Support" / "BambuStudio" / "system" in profiles


def test_windows_uses_the_install_folder_and_appdata(tmp_path):
    host = Host(system="Windows", home=tmp_path,
                env={"PROGRAMFILES": r"C:\Program Files", "APPDATA": r"C:\Users\u\AppData\Roaming"})
    exe = PureWindowsPath(cli_candidates(host)[0][0])
    assert exe.parts[-2:] == ("Bambu Studio", "bambu-studio.exe")
    profiles = [PureWindowsPath(p) for p in profile_candidates(host)]
    assert profiles[0].parts[-4:] == ("Program Files", "Bambu Studio", "resources", "profiles")
    assert profiles[1].parts[-4:] == ("AppData", "Roaming", "BambuStudio", "system")


def test_linux_finds_appimages_and_the_user_copy_of_the_profiles(tmp_path):
    image = tmp_path / "Applications" / "Bambu_Studio_ubuntu-24.04_v02.07.01.62.AppImage"
    image.parent.mkdir()
    image.write_text("", encoding="utf-8")
    host = Host(system="Linux", home=tmp_path, env={})
    assert (str(image),) in cli_candidates(host)
    profiles = profile_candidates(host)
    assert tmp_path / ".config" / "BambuStudio" / "system" in profiles
    flatpak_data = tmp_path / ".var" / "app" / "com.bambulab.BambuStudio" / "config"
    assert flatpak_data / "BambuStudio" / "system" in profiles


def test_profiles_next_to_the_cli_come_first(tmp_path):
    # Bambu Studio finds its resources relative to its executable (<exe>/../../resources on Linux).
    exe = tmp_path / "opt" / "bambu" / "bin" / "bambu-studio"
    host = Host(system="Linux", home=tmp_path, env={})
    beside = profile_candidates(host, (str(exe),))[0]
    # resolve(): Windows runners report tmp_path in 8.3 short form
    assert beside == (tmp_path / "opt" / "bambu" / "resources" / "profiles").resolve()


def test_newest_bundle_wins_and_ties_go_to_the_one_next_to_the_cli(tmp_path):
    exe = tmp_path / "opt" / "bin" / "bambu-studio"
    host = Host(system="Linux", home=tmp_path, env={})
    beside_cli = make_bundle(tmp_path / "opt" / "resources" / "profiles", "02.07.00.08")
    user_copy = make_bundle(tmp_path / ".config" / "BambuStudio" / "system", "02.07.00.08")
    assert find_profiles_dir(host, (str(exe),)) == beside_cli.resolve()

    (user_copy / "BBL.json").write_text(json.dumps({"version": "02.08.00.01"}), encoding="utf-8")
    assert find_profiles_dir(host, (str(exe),)) == user_copy


def test_a_folder_without_bbl_json_is_not_a_bundle(tmp_path):
    (tmp_path / ".config" / "BambuStudio" / "system" / "BBL").mkdir(parents=True)
    assert find_profiles_dir(Host(system="Linux", home=tmp_path, env={})) is None


def test_environment_overrides(tmp_path):
    exe = tmp_path / "bambu-studio"
    exe.write_text("", encoding="utf-8")
    bundle = make_bundle(tmp_path / "profiles", "02.07.00.08")
    host = Host(system="Linux", home=tmp_path, env={CLI_ENV: str(exe), PROFILES_ENV: str(bundle)})
    assert find_cli(host) == (str(exe),)
    assert find_profiles_dir(host) == bundle

    missing = Host(system="Linux", home=tmp_path, env={CLI_ENV: str(tmp_path / "nope")})
    assert find_cli(missing) is None


def test_bundle_version(tmp_path):
    assert bundle_version(make_bundle(tmp_path / "a", "02.07.00.08")) == (2, 7, 0, 8)
    (tmp_path / "b").mkdir()
    assert bundle_version(tmp_path / "b") == ()
