#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Exercise all five tools through the official MCP client's real stdio transport."""
import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import sys

from mcp import Client, StdioServerParameters


async def check(config, source, evidence_file):
    evidence = {"transport": "stdio", "calls": {}}
    server = StdioServerParameters(command=sys.executable, args=["-B", str(Path(__file__).with_name("server.py")), "--config", str(config)])

    def save():
        evidence_file.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")

    async with Client(server) as client:
        response = await client.list_tools()
        evidence["tools"] = [tool.name for tool in response.tools]
        expected = {"server_info", "inspect_3do", "convert_3do_to_blend", "run_regression", "build_extension"}
        if set(evidence["tools"]) != expected:
            raise RuntimeError("Unexpected tool catalog")
        for name, arguments in (("server_info", {}), ("inspect_3do", {"path": str(source)}),
                                ("convert_3do_to_blend", {"path": str(source)}), ("run_regression", {}), ("build_extension", {})):
            result = await client.call_tool(name, arguments)
            data = result.structured_content
            evidence["calls"][name] = data
            save()
            if result.is_error or not isinstance(data, dict) or (name != "server_info" and data.get("status") != "passed"):
                raise RuntimeError(f"{name} failed or returned no structured output: {result}")
            if name == "convert_3do_to_blend":
                digest = hashlib.sha256(Path(data["output"]["path"]).read_bytes()).hexdigest()
                if digest != data["output"]["sha256"]:
                    raise RuntimeError("Independent blend hash mismatch")
            print(f"{name}: passed", flush=True)
        denied = await client.call_tool("inspect_3do", {"path": "../outside.3do"})
        evidence["parent_traversal_rejected"] = denied.is_error
        if not denied.is_error:
            raise RuntimeError("Parent traversal was not rejected")
        evidence["status"] = "passed"
        save()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--input", type=Path, required=True, help="Authorized synthetic 3DO inside a configured read root")
    parser.add_argument("--evidence", type=Path, required=True, help="New JSON file outside Git")
    parser.add_argument("--timeout", type=int, default=600)
    args = parser.parse_args()
    if args.timeout < 1 or args.timeout > 7200:
        parser.error("timeout must be 1..7200 seconds")
    destination = args.evidence.absolute()
    for candidate in (destination, destination.resolve()):
        if any((parent / ".git").exists() for parent in candidate.parents):
            parser.error("Evidence must be outside Git")
    # Exclusive creation prevents overwriting an earlier test receipt.
    with destination.open("x", encoding="utf-8") as stream:
        stream.write('{"status":"started"}\n')
    asyncio.run(asyncio.wait_for(check(args.config.resolve(), args.input.resolve(), destination), timeout=args.timeout))


if __name__ == "__main__":
    main()
