"""pmagent Claude Code hooks.

Each module exposes a ``main()`` that reads the hook payload from stdin and
writes any injected context to stdout. Hooks fail-open: any internal error is
swallowed and the hook exits 0 so the agent is never blocked by a hook bug.

The only way a hook blocks is by explicitly emitting ``exit 2`` in response to
a contract violation. See ``docs/pmagent-hooks-enforcement-design.md``.
"""
