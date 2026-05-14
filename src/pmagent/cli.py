from __future__ import annotations

import argparse
import json
from pathlib import Path

from . import __version__
from .paths import package_root, write_global_config
from .cli_helpers import OBSERVE_SUBCOMMAND_ERROR, _observe_repo_root_args, configure_stdio_utf8
from .cli_helpers import cmd_conflicts, cmd_digest, cmd_export, cmd_install_launchd, cmd_link, cmd_retrieve, cmd_search, cmd_skills_sync, cmd_weekly
from .cli_debate import cmd_debate
from .cli_phases import cmd_clarify, cmd_prd, cmd_research
from .cli_routing import cmd_next, cmd_resume, cmd_review, cmd_route, cmd_start, cmd_status
from .dev import cmd_dev
from .infra import cmd_infra
from . import cli_scaffold as _cli_scaffold
from .cli_scaffold import cmd_init as _cmd_init_impl, cmd_upgrade as _cmd_upgrade_impl
from .cli_workspace import _do_clear, _do_switch, _normalize_workspace_name, cmd_switch, cmd_workspace_close, cmd_workspace_init


__all__ = [
    '_do_clear',
    '_do_switch',
    '_normalize_workspace_name',
    'build_parser',
    'cmd_clarify',
    'cmd_conflicts',
    'cmd_debate',
    'cmd_dev',
    'cmd_digest',
    'cmd_export',
    'cmd_init',
    'cmd_install_launchd',
    'cmd_link',
    'cmd_next',
    'cmd_observe',
    'cmd_hook',
    'cmd_infra',
    'cmd_prd',
    'cmd_research',
    'cmd_resume',
    'cmd_review',
    'cmd_route',
    'cmd_search',
    'cmd_skills_sync',
    'cmd_start',
    'cmd_status',
    'cmd_switch',
    'cmd_upgrade',
    'cmd_weekly',
    'cmd_workspace_close',
    'cmd_workspace_init',
    'main',
    'package_root',
]




def cmd_init(args: argparse.Namespace) -> int:
    _cli_scaffold.write_global_config = write_global_config
    return _cmd_init_impl(args)


def cmd_upgrade(args: argparse.Namespace) -> int:
    return _cmd_upgrade_impl(args)

def cmd_observe(args: argparse.Namespace) -> int:
    from .observation import cli as observation_cli

    remainder = list(args.observe_argv or [])
    if not remainder:
        raise SystemExit(OBSERVE_SUBCOMMAND_ERROR)

    nested_argv = [*_observe_repo_root_args(args.data_dir), *remainder]
    return int(observation_cli.main(nested_argv))


HOOK_MODULES = (
    "session_bootstrap",
    "state_surface",
    "pre_bash_guard",
    "pre_write_guard",
    "post_mutation_check",
    "response_validator",
)


def cmd_hook(args: argparse.Namespace) -> int:
    import importlib

    if args.list_hooks:
        for name in HOOK_MODULES:
            print(name)
        return 0

    name = args.hook_name
    if not name:
        raise SystemExit("pmagent hook: name required (use --list to see available hooks)")
    if name not in HOOK_MODULES:
        raise SystemExit(
            f"pmagent hook: unknown hook '{name}'. Available: {', '.join(HOOK_MODULES)}"
        )
    module = importlib.import_module(f"pmagent.hooks.{name}")
    module.main()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pmagent")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    visible_commands = (
        "init",
        "upgrade",
        "retrieve",
        "link",
        "conflicts",
        "export",
        "digest",
        "search",
        "weekly",
        "status",
        "route",
        "review",
        "start",
        "next",
        "resume",
        "clarify",
        "research",
        "prd",
        "workspace-init",
        "switch",
        "workspace-close",
        "skills-sync",
        "install-launchd",
        "infra",
        "dev",
        "observe",
        "hook",
        "debate",
    )
    sub = parser.add_subparsers(
        dest="command",
        required=True,
        metavar="{" + ",".join(visible_commands) + "}",
    )
    init_p = sub.add_parser("init", help="Initialize ~/.pmagent and the data directory")
    init_p.add_argument("--dir", default=None, help="Target data directory")
    init_p.set_defaults(func=cmd_init)

    upgrade_p = sub.add_parser("upgrade", help="Upgrade managed scaffold files in the data directory")
    upgrade_p.add_argument("--data-dir", default=None)
    upgrade_p.set_defaults(func=cmd_upgrade)

    retrieve_p = sub.add_parser("retrieve", help="Run context retrieval")
    retrieve_p.add_argument("--data-dir", default=None)
    retrieve_p.add_argument("--query", required=True)
    retrieve_p.add_argument("--mode", default="hybrid")
    retrieve_p.add_argument("--project", default=None)
    retrieve_p.add_argument("--global-only", action="store_true")
    retrieve_p.add_argument("--include-memory-index", action="store_true")
    retrieve_p.add_argument("--top-k", type=int, default=8)
    retrieve_p.add_argument("--out", default=None)
    retrieve_p.set_defaults(func=cmd_retrieve)

    link_p = sub.add_parser("link", help="Run auto link")
    link_p.add_argument("--data-dir", default=None)
    link_p.add_argument("--project", default=None)
    link_p.add_argument("--all-projects", action="store_true")
    link_p.add_argument("--file", default=None)
    link_p.add_argument("--reindex", action="store_true")
    link_p.add_argument("--dry-run", action="store_true")
    link_p.set_defaults(func=cmd_link)

    conflicts_p = sub.add_parser("conflicts", help="Detect note conflicts")
    conflicts_p.add_argument("--data-dir", default=None)
    conflicts_p.add_argument("--new", default=None)
    conflicts_p.add_argument("--all", action="store_true")
    conflicts_p.add_argument("--threshold", type=float, default=0.5)
    conflicts_p.add_argument("--out", default=None)
    conflicts_p.set_defaults(func=cmd_conflicts)

    export_p = sub.add_parser("export", help="Export Dev Pack")
    export_p.add_argument("--data-dir", default=None)
    export_p.add_argument("--project", default=None)
    export_p.add_argument("--workspace", default=None)
    export_p.add_argument("--output", default=None)
    export_p.set_defaults(func=cmd_export)

    digest_p = sub.add_parser("digest", help="Generate daily digest")
    digest_p.add_argument("--data-dir", default=None)
    digest_p.add_argument("--config", default=None)
    digest_p.set_defaults(func=cmd_digest)

    search_p = sub.add_parser("search", help="Run ad-hoc web search")
    search_p.add_argument("--data-dir", default=None)
    search_p.add_argument("--query", required=True)
    search_p.add_argument("--count", type=int, default=10)
    search_p.add_argument("--freshness", default="pd")
    search_p.add_argument("--summary", action="store_true")
    search_p.add_argument("--domain-preset", default="general")
    search_p.add_argument("--extra-prefer-domains", nargs="*", default=None)
    search_p.add_argument("--out", default=None)
    search_p.set_defaults(func=cmd_search)

    weekly_p = sub.add_parser("weekly", help="Run the weekly maintenance routine")
    weekly_p.add_argument("--data-dir", default=None)
    weekly_p.set_defaults(func=cmd_weekly)

    status_p = sub.add_parser("status", help="Show the current workspace state and recommended next action")
    status_p.add_argument("--data-dir", default=None)
    status_p.add_argument("--workspace", default=None)
    status_p.add_argument("--next-only", action="store_true")
    status_p.add_argument("--detail", action="store_true")
    status_p.add_argument("--json", action="store_true")
    status_p.set_defaults(func=cmd_status)

    route_p = sub.add_parser("route", help="Recommend skills and commands for the current workspace")
    route_p.add_argument("--data-dir", default=None)
    route_p.add_argument("--project", default=None)
    route_p.add_argument("--workspace", default=None)
    route_p.add_argument("--json", action="store_true")
    route_p.set_defaults(func=cmd_route)

    review_p = sub.add_parser("review", help="Open the most relevant review/status surface for the current workflow phase")
    review_p.add_argument("--data-dir", default=None)
    review_p.add_argument("--workspace", default=None)
    review_p.add_argument("--json", action="store_true")
    review_p.set_defaults(func=cmd_review)

    start_p = sub.add_parser("start", help="Start from the active workspace context with a routed next action")
    start_p.add_argument("--data-dir", default=None)
    start_p.add_argument("--project", default=None)
    start_p.add_argument("--workspace", default=None)
    start_p.add_argument("--description", default=None)
    start_p.add_argument("--requirement-summary", default=None)
    start_p.add_argument(
        "--observation-cadence",
        default="manual",
        choices=["manual", "weekly", "weekday-morning", "daily", "every-12-hours", "every-6-hours"],
    )
    start_p.add_argument("--enable-observation", action="store_true")
    start_p.add_argument("--confirm-cadence", action="store_true")
    start_p.add_argument("--json", action="store_true")
    start_p.set_defaults(func=cmd_start)

    next_p = sub.add_parser("next", help="Show only the recommended next step for the current workspace")
    next_p.add_argument("--data-dir", default=None)
    next_p.add_argument("--workspace", default=None)
    next_p.add_argument("--json", action="store_true")
    next_p.set_defaults(func=cmd_next)

    resume_p = sub.add_parser("resume", help="Resume the active workspace context and show where to continue")
    resume_p.add_argument("--data-dir", default=None)
    resume_p.add_argument("--project", default=None)
    resume_p.add_argument("--workspace", default=None)
    resume_p.add_argument("--json", action="store_true")
    resume_p.set_defaults(func=cmd_resume)

    clarify_p = sub.add_parser("clarify", help="Drive one-question-at-a-time clarifying flow for the active workspace")
    clarify_p.add_argument("--data-dir", default=None)
    clarify_sub = clarify_p.add_subparsers(dest="subcommand", required=True)

    clarify_status_p = clarify_sub.add_parser("status", help="Show the current clarifying readiness and transition recommendation")
    clarify_status_p.add_argument("--workspace", default=None)
    clarify_status_p.add_argument("--json", action="store_true")
    clarify_status_p.set_defaults(func=cmd_clarify)

    clarify_answer_p = clarify_sub.add_parser("answer", help="Record one clarifying answer")
    clarify_answer_p.add_argument("--workspace", default=None)
    clarify_answer_p.add_argument("--answer", required=True)
    clarify_answer_p.add_argument("--json", action="store_true")
    clarify_answer_p.set_defaults(func=cmd_clarify)

    clarify_scores_p = clarify_sub.add_parser("set-scores", help="Apply clarifying readiness scores and gates from an external agent patch")
    clarify_scores_p.add_argument("--workspace", default=None)
    clarify_scores_p.add_argument("--patch-file", type=Path, required=True)
    clarify_scores_p.add_argument("--json", action="store_true")
    clarify_scores_p.set_defaults(func=cmd_clarify)

    research_p = sub.add_parser("research", help="Track research readiness and log evidence for the active workspace")
    research_p.add_argument("--data-dir", default=None)
    research_sub = research_p.add_subparsers(dest="subcommand", required=True)

    research_status_p = research_sub.add_parser("status", help="Show research readiness for the current workspace")
    research_status_p.add_argument("--workspace", default=None)
    research_status_p.add_argument("--json", action="store_true")
    research_status_p.set_defaults(func=cmd_research)

    research_start_p = research_sub.add_parser("start", help="Confirm the clarifying-to-researching phase transition")
    research_start_p.add_argument("--workspace", default=None)
    research_start_p.add_argument("--json", action="store_true")
    research_start_p.set_defaults(func=cmd_research)

    research_note_p = research_sub.add_parser("note", help="Append one research note and refresh research readiness")
    research_note_p.add_argument("--workspace", default=None)
    research_note_p.add_argument("--title", default=None)
    research_note_p.add_argument("--summary", required=True)
    research_note_p.add_argument("--source", default=None)
    research_note_p.add_argument("--json", action="store_true")
    research_note_p.set_defaults(func=cmd_research)

    research_scores_p = research_sub.add_parser("set-scores", help="Apply research readiness scores and gates from an external agent patch")
    research_scores_p.add_argument("--workspace", default=None)
    research_scores_p.add_argument("--patch-file", type=Path, required=True)
    research_scores_p.add_argument("--json", action="store_true")
    research_scores_p.set_defaults(func=cmd_research)

    prd_p = sub.add_parser("prd", help="Guided PRD workflow entrypoints")
    prd_p.add_argument("--data-dir", default=None)
    prd_sub = prd_p.add_subparsers(dest="subcommand", required=True)

    prd_status_sub = prd_sub.add_parser("status", help="Show PRD readiness and handoff state")
    prd_status_sub.add_argument("--workspace", default=None)
    prd_status_sub.add_argument("--json", action="store_true")
    prd_status_sub.set_defaults(func=cmd_prd)

    prd_review_sub = prd_sub.add_parser("review", help="Show PRD post-draft handoff options")
    prd_review_sub.add_argument("--workspace", default=None)
    prd_review_sub.add_argument("--json", action="store_true")
    prd_review_sub.set_defaults(func=cmd_prd)

    prd_challenge_sub = prd_sub.add_parser("challenge", help="Show the explicit PRD challenge surface and downstream choices")
    prd_challenge_sub.add_argument("--workspace", default=None)
    prd_challenge_sub.add_argument("--json", action="store_true")
    prd_challenge_sub.set_defaults(func=cmd_prd)

    prd_init_sub = prd_sub.add_parser("init-draft", help="Create the first canonical PRD draft from the template")
    prd_init_sub.add_argument("--workspace", default=None)
    prd_init_sub.add_argument("--json", action="store_true")
    prd_init_sub.set_defaults(func=cmd_prd)

    workspace_init_p = sub.add_parser(
        "workspace-init",
        help="Create or update a project/workspace scaffold and initialize observation",
    )
    workspace_init_p.add_argument("--data-dir", default=None)
    workspace_init_p.add_argument("--project", required=True)
    workspace_init_p.add_argument("--workspace", default=None)
    workspace_init_p.add_argument("--description", default=None)
    workspace_init_p.add_argument("--requirement-summary", default=None)
    workspace_init_p.add_argument("--priority", default="P1", choices=["P0", "P1", "P2"])
    workspace_init_p.add_argument(
        "--status",
        default="drafting",
        choices=["drafting", "in-progress", "reviewing", "completed", "on-hold"],
    )
    workspace_init_p.add_argument("--keywords", nargs="*", default=None)
    workspace_init_p.add_argument(
        "--observation-cadence",
        default="manual",
        choices=["manual", "weekly", "weekday-morning", "daily", "every-12-hours", "every-6-hours"],
    )
    workspace_init_p.add_argument("--enable-observation", action="store_true")
    workspace_init_p.add_argument("--confirm-cadence", action="store_true")
    workspace_init_p.add_argument("--no-infra-bootstrap", action="store_true")
    workspace_init_p.set_defaults(func=cmd_workspace_init)

    switch_p = sub.add_parser("switch", help="Switch active project/workspace isolation")
    switch_p.add_argument("--data-dir", default=None)
    switch_p.add_argument("project", nargs="?")
    switch_p.add_argument("workspace", nargs="?")
    switch_p.add_argument("--list", action="store_true")
    switch_p.add_argument("--clear", action="store_true")
    switch_p.set_defaults(func=cmd_switch)

    workspace_close_p = sub.add_parser("workspace-close", help="Finalize a workspace for this round and emit global promotion candidates")
    workspace_close_p.add_argument("--data-dir", default=None)
    workspace_close_p.add_argument("--workspace", required=True)
    workspace_close_p.add_argument("--json", action="store_true")
    workspace_close_p.set_defaults(func=cmd_workspace_close)

    skills_p = sub.add_parser("skills-sync", help="Sync packaged skills into the data directory")
    skills_p.add_argument("--data-dir", default=None)
    skills_p.add_argument("--output-dir", default=None)
    skills_p.set_defaults(func=cmd_skills_sync)

    launchd_p = sub.add_parser("install-launchd", help="Install launchd plist files")
    launchd_p.add_argument("--data-dir", default=None)
    launchd_p.add_argument("job", choices=["daily-digest", "weekly-routine"])
    launchd_p.add_argument("--weekday", type=int, default=None)
    launchd_p.add_argument("--hour", type=int, default=None)
    launchd_p.add_argument("--minute", type=int, default=None)
    launchd_p.set_defaults(func=cmd_install_launchd)

    infra_p = sub.add_parser("infra", help="PM Infra protocol, card relay, and Git boundary helpers")
    infra_p.add_argument("--data-dir", default=None)
    infra_sub = infra_p.add_subparsers(dest="subcommand", required=True)

    infra_protocol_p = infra_sub.add_parser("protocol", help="Write full PM Infra protocol artifacts")
    infra_protocol_p.add_argument("--project", default=None)
    infra_protocol_p.add_argument("--workspace", default=None)
    infra_protocol_p.add_argument("--json", action="store_true")
    infra_protocol_p.set_defaults(func=cmd_infra)

    infra_auth_p = infra_sub.add_parser("auth-guide", help="Show minimal lark-cli auth scopes and setup commands")
    infra_auth_p.add_argument("--profile", default="pma-feishu")
    infra_auth_p.add_argument("--app-id", default=None)
    infra_auth_p.add_argument("--brand", default="lark", choices=["lark", "feishu"])
    infra_auth_p.add_argument("--json", action="store_true")
    infra_auth_p.set_defaults(func=cmd_infra)

    infra_bootstrap_p = infra_sub.add_parser("bootstrap", help="Create or bind project-level Feishu Wiki/Base infrastructure")
    infra_bootstrap_p.add_argument("--project", required=True)
    infra_bootstrap_p.add_argument("--base-token", default=None, help="Existing Feishu Base app token to adopt")
    infra_bootstrap_p.add_argument("--table-id", default=None, help="Existing Candidate Cards table id to adopt")
    infra_bootstrap_p.add_argument("--adopt-existing-base", action="store_true")
    infra_bootstrap_p.add_argument("--dry-run", action="store_true")
    infra_bootstrap_p.add_argument("--json", action="store_true")
    infra_bootstrap_p.set_defaults(func=cmd_infra)

    infra_sync_status_p = infra_sub.add_parser("sync-status", help="Show pending Feishu Wiki mirror files")
    infra_sync_status_p.add_argument("--project", default=None)
    infra_sync_status_p.add_argument("--workspace", default=None)
    infra_sync_status_p.add_argument("--command", default=None, help="Use a custom Feishu Wiki push command for this check")
    infra_sync_status_p.add_argument("--json", action="store_true")
    infra_sync_status_p.set_defaults(func=cmd_infra)

    infra_wiki_push_p = infra_sub.add_parser("wiki-push", help="Push whitelisted PM Data Markdown files through the Feishu Wiki adapter")
    infra_wiki_push_p.add_argument("--project", default=None)
    infra_wiki_push_p.add_argument("--workspace", default=None)
    infra_wiki_push_p.add_argument("--command", default=None, help="Optional custom command template; may use {file}, {relative}, {workspace}, {project}, {data_dir}")
    infra_wiki_push_p.add_argument("--all", action="store_true", help="Push all whitelisted files instead of only pending files")
    infra_wiki_push_p.add_argument("--dry-run", action="store_true")
    infra_wiki_push_p.add_argument("--json", action="store_true")
    infra_wiki_push_p.set_defaults(func=cmd_infra)

    infra_pull_p = infra_sub.add_parser("pull-cards", help="Import Candidate Cards into local inbox")
    infra_pull_p.add_argument("--from", dest="from_file", default=None, help="Candidate Card JSON file")
    infra_pull_p.add_argument("--from-base", action="store_true", help="Pull Candidate Cards directly from Feishu Base")
    infra_pull_p.add_argument("--base-token", default=None, help="Override PMAGENT_FEISHU_BASE_APP_TOKEN")
    infra_pull_p.add_argument("--table-id", default=None, help="Override PMAGENT_FEISHU_CARDS_TABLE_ID")
    infra_pull_p.add_argument("--project", default=None)
    infra_pull_p.add_argument("--workspace", default=None)
    infra_pull_p.add_argument("--json", action="store_true")
    infra_pull_p.set_defaults(func=cmd_infra)

    infra_review_p = infra_sub.add_parser("review-card", help="Record local review feedback for a Candidate Card")
    infra_review_p.add_argument("--workspace", default=None)
    infra_review_p.add_argument("--card", required=True)
    infra_review_p.add_argument("--status", required=True, choices=["accepted", "rejected", "snoozed"])
    infra_review_p.add_argument("--note", default="")
    infra_review_p.add_argument("--json", action="store_true")
    infra_review_p.set_defaults(func=cmd_infra)

    infra_feedback_p = infra_sub.add_parser("push-feedback", help="Write local Candidate Card review feedback back to Feishu Base")
    infra_feedback_p.add_argument("--workspace", default=None)
    infra_feedback_p.add_argument("--base-token", default=None, help="Override PMAGENT_FEISHU_BASE_APP_TOKEN")
    infra_feedback_p.add_argument("--table-id", default=None, help="Override PMAGENT_FEISHU_CARDS_TABLE_ID")
    infra_feedback_p.add_argument("--json", action="store_true")
    infra_feedback_p.set_defaults(func=cmd_infra)

    infra_github_p = infra_sub.add_parser("github-push", help="Commit and push the PM Data directory to its GitHub mirror")
    infra_github_p.add_argument("--remote", default=None, help="Override PMAGENT_GITHUB_REMOTE")
    infra_github_p.add_argument("--branch", default="main")
    infra_github_p.add_argument("--message", default=None)
    infra_github_p.add_argument("--json", action="store_true")
    infra_github_p.set_defaults(func=cmd_infra)

    infra_git_p = infra_sub.add_parser("git-boundary", help="Show whether the PM Data directory is its own Git repo")
    infra_git_p.add_argument("--json", action="store_true")
    infra_git_p.set_defaults(func=cmd_infra)

    dev_p = sub.add_parser("dev", help="Development-side slice evidence and review helpers")
    dev_p.add_argument("--data-dir", default=None)
    dev_sub = dev_p.add_subparsers(dest="subcommand", required=True)

    dev_slices_p = dev_sub.add_parser("slices", help="List dev slices for a workspace")
    dev_slices_p.add_argument("--workspace", default=None)
    dev_slices_p.add_argument("--json", action="store_true")
    dev_slices_p.set_defaults(func=cmd_dev)

    dev_run_p = dev_sub.add_parser("run-record", help="Record slice run evidence and optional lesson candidate")
    dev_run_p.add_argument("--workspace", default=None)
    dev_run_p.add_argument("--slice", required=True)
    dev_run_p.add_argument("--command", required=True)
    dev_run_p.add_argument("--status", required=True, choices=["passed", "failed", "blocked"])
    dev_run_p.add_argument("--lesson", default=None)
    dev_run_p.add_argument("--json", action="store_true")
    dev_run_p.set_defaults(func=cmd_dev)

    dev_lessons_p = dev_sub.add_parser("lesson-review", help="Show slice lesson candidates waiting for review")
    dev_lessons_p.add_argument("--workspace", default=None)
    dev_lessons_p.add_argument("--lesson-id", default=None, help="Review one lesson candidate instead of listing")
    dev_lessons_p.add_argument("--status", choices=["accepted", "rejected", "deferred"], default=None)
    dev_lessons_p.add_argument("--note", default="")
    dev_lessons_p.add_argument("--json", action="store_true")
    dev_lessons_p.set_defaults(func=cmd_dev)

    observe_p = sub.add_parser("observe", help="Run workspace observation workflows")
    observe_p.add_argument("--data-dir", default=None)
    observe_p.add_argument(
        "observe_argv",
        nargs=argparse.REMAINDER,
        help="Observation subcommand and arguments, e.g. run --workspace demo",
    )
    observe_p.set_defaults(func=cmd_observe)

    hook_p = sub.add_parser(
        "hook",
        help="Run a pmagent Claude Code hook (invoked from .claude/settings.json)",
    )
    hook_p.add_argument("hook_name", nargs="?", default=None)
    hook_p.add_argument("--list", dest="list_hooks", action="store_true")
    hook_p.set_defaults(func=cmd_hook)

    debate_p = sub.add_parser("debate", help="Run Debate workflow entrypoints")
    debate_p.add_argument("--data-dir", default=None)
    debate_sub = debate_p.add_subparsers(dest="subcommand", required=True)

    debate_start_p = debate_sub.add_parser("start", help="Initialize a new debate topic")
    debate_start_p.add_argument("--workspace", default=None)
    debate_start_p.add_argument("--thesis", required=True)
    debate_start_p.add_argument("--topic-slug", default=None)
    debate_start_p.add_argument("--rounds", type=int, default=3)
    debate_start_p.add_argument("--axis", required=True)
    debate_start_p.add_argument("--force", action="store_true")
    debate_start_p.add_argument("--foreground", action="store_true", help="Run the debate synchronously instead of launching a background worker")
    debate_start_p.add_argument("--pro-exec", default=None)
    debate_start_p.add_argument("--con-exec", default=None)
    debate_start_p.add_argument("--synth-exec", default=None)
    debate_start_p.add_argument("--pro-model", default=None)
    debate_start_p.add_argument("--con-model", default=None)
    debate_start_p.add_argument("--synth-model", default=None)
    debate_start_p.add_argument("--json", action="store_true")
    debate_start_p.set_defaults(func=cmd_debate)

    debate_status_p = debate_sub.add_parser("status", help="Show debate topic state")
    debate_status_p.add_argument("--workspace", default=None)
    debate_status_p.add_argument("--topic", default=None)
    debate_status_p.add_argument("--json", action="store_true")
    debate_status_p.set_defaults(func=cmd_debate)

    debate_show_p = debate_sub.add_parser("show", help="Show a debate round or synthesis")
    debate_show_p.add_argument("--workspace", default=None)
    debate_show_p.add_argument("--topic", required=True)
    debate_show_group = debate_show_p.add_mutually_exclusive_group()
    debate_show_group.add_argument("--round", type=int, default=None, help="1-indexed round number; use 1 for the first round")
    debate_show_group.add_argument("--synthesis", action="store_true")
    debate_show_p.add_argument("--side", choices=["defender", "attacker"], default="defender")
    debate_show_p.add_argument("--json", action="store_true")
    debate_show_p.set_defaults(func=cmd_debate)

    debate_review_p = debate_sub.add_parser("review", help="Mark a debate topic as actively under review")
    debate_review_p.add_argument("--workspace", default=None)
    debate_review_p.add_argument("--topic", required=True)
    debate_review_p.add_argument("--json", action="store_true")
    debate_review_p.set_defaults(func=cmd_debate)

    debate_resolve_p = debate_sub.add_parser("resolve", help="Resolve a debate review outcome")
    debate_resolve_p.add_argument("--workspace", default=None)
    debate_resolve_p.add_argument("--topic", required=True)
    debate_resolve_group = debate_resolve_p.add_mutually_exclusive_group(required=True)
    debate_resolve_group.add_argument("--accepted", action="store_true")
    debate_resolve_group.add_argument("--rejected", action="store_true")
    debate_resolve_group.add_argument("--deferred", action="store_true")
    debate_resolve_p.add_argument("--notes", default=None)
    debate_resolve_p.add_argument("--json", action="store_true")
    debate_resolve_p.set_defaults(func=cmd_debate)

    debate_run_p = debate_sub.add_parser("_run-topic", help=argparse.SUPPRESS)
    debate_run_p.add_argument("--workspace", required=True)
    debate_run_p.add_argument("--topic", required=True)
    debate_run_p.set_defaults(func=cmd_debate)

    return parser


def main(argv: list[str] | None = None) -> int:
    configure_stdio_utf8()
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
