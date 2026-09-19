#!/usr/bin/env python3
"""
AI text-to-3D and image-to-3D with Meshy, Tripo or Hyper3D Rodin.

The prompt is sent exactly as written. The default output is the provider's textured
GLB, untouched: Bambu Studio 2.7+ opens GLB files and turns the texture into paint.

Usage:
  python3 scripts/generate.py text "a small dragon figurine" --wait
  python3 scripts/generate.py image photo.png --wait --height 60
  python3 scripts/generate.py status <task id>
  python3 scripts/generate.py download <task id> [--format stl] [--height 60]

A task id looks like meshy:text:0193… and is all that is needed to check or resume a
task later. Waiting never spends credits: if --timeout runs out, the task keeps running
at the provider and `download <task id>` picks it up.

Exit codes: 0 ok (including "still running") · 1 generation or download failed ·
2 bad arguments or no API key · 3 missing dependency.
"""

import argparse
import json
import os
import sys
from pathlib import Path

from bambu_studio_ai.generation.errors import DependencyError, InputError, ProviderError
from bambu_studio_ai.generation.inputs import load_image
from bambu_studio_ai.generation.ledger import FollowUpLedger
from bambu_studio_ai.generation.pipeline import GenerationResult, Generator
from bambu_studio_ai.generation.providers import PROVIDER_NAMES, ProviderSettings, create_provider
from bambu_studio_ai.generation.providers.base import OUTPUT_FORMATS, GenerationRequest, TaskRef
from common import get_config, home_dir, load_config, output_dir, use_utf8_stdio

EXIT_OK, EXIT_FAILED, EXIT_CONFIG, EXIT_DEPENDENCY = 0, 1, 2, 3
LIBRARY_ERRORS = (InputError, DependencyError, ProviderError)
DEFAULT_TIMEOUT_S = 900.0
SCRIPT = "python3 scripts/generate.py"

REMOVED_FLAGS = {
    "--raw": "Prompts are no longer rewritten, so there is nothing to turn off: the prompt is "
             "sent to the provider exactly as written. Put printing requirements in the prompt "
             "yourself (see references/3d-prompt-guide.md).",
    "--auto-retry": "Automatic re-generation was removed: it started new paid generations, even "
                    "when a generation was merely slow. Check the model with analyze.py and "
                    "decide whether to generate again.",
    "--style": "Meshy ignores art_style since Meshy-6. Choose a model with --model instead.",
    "--no-bg-remove": "Background removal was removed; providers isolate the subject "
                      "themselves. Crop the photo to one object on a plain background instead.",
}
REMOVED_PROVIDERS = {
    "printpal": "Printpal support was removed: the code called routes and formats that "
                "Printpal's API does not have.",
    "3daistudio": "3D AI Studio support was removed: the code called routes that do not exist.",
}
REMOVED_NOTE = "\nSupported providers: {names}. Set one with: python3 scripts/configure.py set 3d_provider meshy"


def removed_flag(argv):
    """The first removed flag in argv, if any."""
    for arg in argv:
        name = arg.split("=", 1)[0]
        if name in REMOVED_FLAGS:
            return name
    return None


def emit(data, *, as_json):
    """Print the one JSON document (``--json``) that is the command's result."""
    if as_json:
        print(json.dumps(data))


def human(message, *, as_json):
    """Human output: stdout normally, stderr under --json so stdout stays one document."""
    print(message, file=sys.stderr if as_json else sys.stdout)


def fail(message, code, *, as_json, kind, task_id=None, resume=None):
    """Report an error on stderr (and as JSON on stdout with --json); return the exit code."""
    emit({"error": {"type": kind, "message": message}, "task_id": task_id, "next_command": resume},
         as_json=as_json)
    print(f"❌ {message}", file=sys.stderr)
    if resume:
        print(f"   The task keeps its id; retry with: {resume}", file=sys.stderr)
    return code


def fail_from(exc, *, as_json, task_id=None, resume=None):
    """Map a library exception to its exit code and report it."""
    if isinstance(exc, InputError):
        code, kind, message = EXIT_CONFIG, "bad_input", str(exc)
    elif isinstance(exc, DependencyError):
        code, kind, message = EXIT_DEPENDENCY, "dependency", str(exc)
    else:
        code, kind, message = EXIT_FAILED, "provider", f"{exc.message} [{exc.code}]"
    return fail(message, code, as_json=as_json, kind=kind, task_id=task_id, resume=resume)


def api_key(provider, config):
    """BAMBU_3D_API_KEY, else <provider>_api_key, else 3d_api_key. Never printed."""
    return (os.environ.get("BAMBU_3D_API_KEY")
            or str(config.get(f"{provider}_api_key") or config.get("3d_api_key") or ""))


def build_generator(provider_name, config, *, as_json):
    """The configured provider wrapped in a Generator, or an exit code if it can't be built."""
    if provider_name in REMOVED_PROVIDERS:
        message = REMOVED_PROVIDERS[provider_name] + REMOVED_NOTE.format(names=", ".join(PROVIDER_NAMES))
        return None, fail(message, EXIT_CONFIG, as_json=as_json, kind="removed_provider")
    if provider_name not in PROVIDER_NAMES:
        return None, fail(f"unknown provider {provider_name!r}; choose one of {', '.join(PROVIDER_NAMES)}",
                          EXIT_CONFIG, as_json=as_json, kind="bad_input")
    key = api_key(provider_name, config)
    if not key:
        hint = (f"No API key for {provider_name}. Save it with: python3 scripts/configure.py "
                f"secret {provider_name}_api_key   (it prompts for the key, or reads it from stdin)")
        return None, fail(hint, EXIT_CONFIG, as_json=as_json, kind="not_configured")
    options = {"rodin_tier": str(get_config("BAMBU_RODIN_TIER", config, "rodin_tier") or "")}
    provider = create_provider(provider_name, ProviderSettings(api_key=key, options=options))
    notify = (lambda message: print(f"⏳ {message}", file=sys.stderr))
    generator = Generator(provider, output_dir=Path(output_dir("models", create=False)),
                          ledger=FollowUpLedger(Path(home_dir()) / "generation-tasks.json"),
                          notify=notify)
    return generator, EXIT_OK


def resume_flags(args):
    """The download flags that reproduce this command's result when resuming."""
    flags = []
    if getattr(args, "format", "glb") != "glb":
        flags += ["--format", args.format]
    if getattr(args, "height", None):
        flags += ["--height", f"{args.height:g}"]
    if getattr(args, "no_texture", False):
        flags.append("--no-texture")
    return " ".join(flags)


def next_command(verb, result, args):
    extra = resume_flags(args) if verb == "download" else ""
    return f"{SCRIPT} {verb} {result.task_id}" + (f" {extra}" if extra else "")


def report(result: GenerationResult, args, *, as_json, submitted_only=False):
    """Print a result (human lines and/or the JSON document); return the exit code."""
    data = result.to_dict()
    if result.still_running:
        data["next_command"] = next_command("download", result, args)
    emit(data, as_json=as_json)

    def say(message):
        human(message, as_json=as_json)

    if submitted_only:
        say(f"📤 Submitted to {result.provider}. Task id: {result.task_id}")
        say(f"   Check:    {next_command('status', result, args)}")
        say(f"   Download: {next_command('download', result, args)}")
        return EXIT_OK
    if result.still_running:
        progress = f" ({result.progress}%)" if result.progress is not None else ""
        say(f"⏳ Still {result.status}{progress} at {result.provider}; nothing was resubmitted "
            f"and no extra credits were used. {result.message}".rstrip())
        say(f"   Resume with: {data['next_command']}")
        return EXIT_OK
    if result.status != "succeeded":
        say(f"❌ Task {result.task_id} ended as {result.status}: {result.message or 'no reason given'}")
        return EXIT_FAILED
    size = " × ".join(f"{value:.1f}" for value in result.extents_mm or ())
    colour = "textured" if result.has_texture else "no colour"
    say(f"✅ {result.output_format.upper()} saved ({size} mm, X × Y × Z; {colour})")
    for warning in result.warnings:
        say(f"⚠️ {warning}")
    say(f"➡️ Use this file: {result.output_file}")
    return EXIT_OK


def check_numbers(args):
    if getattr(args, "height", None) is not None and args.height <= 0:
        raise InputError("--height must be a positive number of millimetres")
    if getattr(args, "timeout", 1) <= 0:
        raise InputError("--timeout must be a positive number of seconds")


def cmd_generate(args, config):
    """text / image: submit, then optionally wait and download."""
    as_json = args.json
    check_numbers(args)
    image = load_image(args.image) if args.command == "image" else None  # before any network call
    provider_name = (args.provider or get_config("BAMBU_3D_PROVIDER", config, "3d_provider", "meshy")).lower()
    generator, code = build_generator(provider_name, config, as_json=as_json)
    if generator is None:
        return code
    provider = generator.provider
    prompt = args.prompt if args.command == "text" else (args.prompt or None)
    prompt_used = None
    if image is not None:
        prompt_used = bool(prompt) and provider.image_prompt_supported
        if prompt and not prompt_used:
            print(f"⚠️ {provider.name} image-to-3D has no prompt field; --prompt was not sent.", file=sys.stderr)
    texture = not args.no_texture and args.format == "glb"
    if args.format != "glb" and not args.no_texture:
        print(f"ℹ️ {args.format.upper()} carries no colour, so no texture is generated (saves credits).",
              file=sys.stderr)
    request = GenerationRequest(prompt=prompt, image=image, model=args.model,
                                output_format=args.format, texture=texture)
    if image is not None and image.data is not None:
        print(f"📤 Uploading {image.name} to {provider.name} (the image leaves this computer).",
              file=sys.stderr)
    try:
        ref = generator.submit(request)
    except ProviderError as exc:
        # A dropped connection may hide a task the provider did start (and bill).
        note = (" The request may still have reached the provider: check its dashboard before "
                "submitting again, to avoid paying twice." if exc.code == "network" else "")
        return fail(f"{exc.message} [{exc.code}]{note}", EXIT_FAILED, as_json=as_json, kind="provider")
    if not args.wait:
        result = GenerationResult(ref.token, ref.provider, "submitted", prompt_used=prompt_used)
        return report(result, args, as_json=as_json, submitted_only=True)
    print(f"📤 Task id: {ref.token} (waiting up to {args.timeout:.0f} s)", file=sys.stderr)
    try:
        result = generator.complete(ref, output_format=args.format, texture=texture,
                                    height_mm=args.height, timeout_s=args.timeout,
                                    first_delay_s=provider.poll_interval_s)
    except LIBRARY_ERRORS as exc:
        resume = f"{SCRIPT} download {ref.token} {resume_flags(args)}".rstrip()
        return fail_from(exc, as_json=as_json, task_id=ref.token, resume=resume)
    result.prompt_used = prompt_used
    return report(result, args, as_json=as_json)


def cmd_task(args, config):
    """status / download: resume a task from its id."""
    as_json = args.json
    check_numbers(args)
    ref = TaskRef.parse(args.task_id)
    generator, code = build_generator(ref.provider, config, as_json=as_json)
    if generator is None:
        return code
    if args.command == "status":
        result = generator.status(ref)
        data = result.to_dict()
        if result.still_running:
            data["next_command"] = next_command("download", result, args)
        emit(data, as_json=as_json)
        progress = f" {result.progress}%" if result.progress is not None else ""
        human(f"{result.task_id}: {result.status}{progress}"
              + (f" ({result.message})" if result.message else ""), as_json=as_json)
        return EXIT_OK
    texture = not args.no_texture and args.format == "glb"
    try:
        result = generator.complete(ref, output_format=args.format, texture=texture,
                                    height_mm=args.height, timeout_s=args.timeout)
    except LIBRARY_ERRORS as exc:
        resume = f"{SCRIPT} download {ref.token} {resume_flags(args)}".rstrip()
        return fail_from(exc, as_json=as_json, task_id=ref.token, resume=resume)
    return report(result, args, as_json=as_json)


def add_output_options(parser):
    parser.add_argument("--format", choices=OUTPUT_FORMATS, default="glb",
                        help="glb (default): the provider's textured model, which Bambu Studio 2.7+ "
                             "opens with its colours. stl/3mf/obj: geometry only, converted by the "
                             "provider where it can (else locally, discarding colour)")
    parser.add_argument("--height", type=float, metavar="MM",
                        help="scale the model so its height (Z, as Bambu Studio imports it) is MM; "
                             "without it the provider's size is kept")
    parser.add_argument("--no-texture", action="store_true",
                        help="skip the texture (cheaper; e.g. Meshy skips its 10-credit refine step)")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_S, metavar="SECONDS",
                        help=f"how long to wait (default {DEFAULT_TIMEOUT_S:.0f}); the task keeps "
                             "running after that and can be resumed with download")
    parser.add_argument("--json", action="store_true", help="print one JSON object on stdout")


def build_parser():
    parser = argparse.ArgumentParser(
        description="AI text/image-to-3D (Meshy, Tripo, Hyper3D Rodin). Prompts are sent as written.",
        epilog="Keys: python3 scripts/configure.py secret <provider>_api_key. "
               "Default provider: config 3d_provider (meshy).")
    sub = parser.add_subparsers(dest="command", required=True)
    for name, help_text in (("text", "generate from a text prompt"),
                            ("image", "generate from a photo or drawing (local file or http(s) URL)")):
        command = sub.add_parser(name, help=help_text)
        if name == "text":
            command.add_argument("prompt", help="what to make, sent to the provider unchanged")
        else:
            command.add_argument("image", help="PNG/JPEG/WebP path or http(s) URL (max 20 MB)")
            command.add_argument("--prompt", help="optional guidance; only Rodin uses it for images")
        command.add_argument("--provider", help=f"one of {', '.join(PROVIDER_NAMES)} (default: config)")
        command.add_argument("--model", help="provider model/tier, e.g. meshy-6, v3.0-20250812, "
                                             "Gen-2.5-High (default: the provider's current one)")
        command.add_argument("--wait", action="store_true", help="wait for the model and download it")
        add_output_options(command)
    status = sub.add_parser("status", help="check a task once (never starts or pays for anything)")
    status.add_argument("task_id", help="the task id printed when the task was submitted")
    status.add_argument("--json", action="store_true", help="print one JSON object on stdout")
    download = sub.add_parser("download", help="wait for a task if needed, then download it")
    download.add_argument("task_id", help="the task id printed when the task was submitted")
    add_output_options(download)
    return parser


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    flag = removed_flag(argv)
    if flag:
        print(f"`{flag}` was removed in v2.1. {REMOVED_FLAGS[flag]}", file=sys.stderr)
        return EXIT_CONFIG
    args = build_parser().parse_args(argv)
    as_json = getattr(args, "json", False)
    config = load_config(include_secrets=True)
    handler = cmd_task if args.command in ("status", "download") else cmd_generate
    try:
        return handler(args, config)
    except LIBRARY_ERRORS as exc:
        return fail_from(exc, as_json=as_json, task_id=getattr(args, "task_id", None))


if __name__ == "__main__":
    use_utf8_stdio()
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nInterrupted. Any submitted task keeps running; resume it with generate.py download.",
              file=sys.stderr)
        sys.exit(130)
