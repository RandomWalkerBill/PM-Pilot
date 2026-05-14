from __future__ import annotations

from pathlib import Path


def project_root(repo_root: Path, project: str) -> Path:
    return repo_root / "projects" / project


def project_state_root(repo_root: Path, project: str) -> Path:
    return project_root(repo_root, project) / ".pmagent"


def project_state_path(repo_root: Path, project: str) -> Path:
    return project_state_root(repo_root, project) / "project-state.json"


def workspace_root(repo_root: Path, workspace: str) -> Path:
    return repo_root / "workspaces" / workspace


def observations_root(repo_root: Path) -> Path:
    return repo_root / "observations"


def project_observation_root(repo_root: Path, project: str) -> Path:
    return observations_root(repo_root) / project


def project_observation_index_path(repo_root: Path, project: str) -> Path:
    return project_observation_root(repo_root, project) / "index.json"


def project_observation_policy_path(repo_root: Path, project: str) -> Path:
    return project_observation_root(repo_root, project) / "policy.json"


def project_observation_state_path(repo_root: Path, project: str) -> Path:
    return project_observation_root(repo_root, project) / "state.json"


def project_observation_files_root(repo_root: Path, project: str) -> Path:
    return project_observation_root(repo_root, project) / "files"


def project_observation_runs_root(repo_root: Path, project: str) -> Path:
    return project_observation_root(repo_root, project) / "runs"


def observation_file_path(repo_root: Path, project: str, observation_id: str) -> Path:
    return project_observation_files_root(repo_root, project) / f"{observation_id}.json"


def workspace_summary_path(repo_root: Path, workspace: str) -> Path:
    return workspace_root(repo_root, workspace) / "workspace-summary.md"


def prd_root(repo_root: Path, workspace: str) -> Path:
    return workspace_root(repo_root, workspace) / "prd"


def candidate_updates_root(repo_root: Path, workspace: str) -> Path:
    return workspace_root(repo_root, workspace) / "candidate-updates"


def queue_summary_path(repo_root: Path, workspace: str) -> Path:
    return candidate_updates_root(repo_root, workspace) / "queue-summary.json"


def maintenance_root(repo_root: Path, workspace: str) -> Path:
    return workspace_root(repo_root, workspace) / "maintenance"


def maintenance_drafts_root(repo_root: Path, workspace: str) -> Path:
    return maintenance_root(repo_root, workspace) / "drafts"


def maintenance_changelog_root(repo_root: Path, workspace: str) -> Path:
    return maintenance_root(repo_root, workspace) / "changelog"


def maintenance_consumed_root(repo_root: Path, workspace: str) -> Path:
    return maintenance_root(repo_root, workspace) / "consumed-cards"
