"""Dramatiq tasks for processing GitHub issues."""

import dramatiq
from task_queue.broker import broker
from logger import get_logger

logger = get_logger(__name__)

dramatiq.set_broker(broker)


@dramatiq.actor(queue_name="github_coder", max_retries=3, time_limit=3600000)
def process_github_issue(issue_data: dict) -> None:
    """
    Process a GitHub issue with the coder agent.
    
    This task is enqueued by the event publisher service and consumed by worker instances.
    
    Args:
        issue_data: Dictionary containing issue information (owner, repo, issue_number, etc.)
    """
    from services.github.issue_payload import IssueOpenedForCoder
    from agents.github_coder import run_agent_on_issue
    from services.github.coder_workflow import (
        _transition_in_progress_to_done,
        _transition_in_progress_to_error,
    )
    from services.github.client import comment_on_issue
    from services.github.installation_token import get_api_token_for_coder_issue
    
    logger.info(
        "Worker processing issue: %s/%s#%s",
        issue_data.get("owner"),
        issue_data.get("repo_name"),
        issue_data.get("issue_number"),
    )
    
    try:
        work = IssueOpenedForCoder(**issue_data)
        tok = get_api_token_for_coder_issue(
            work.owner,
            work.repo_name,
            github_installation_id=work.github_installation_id,
        )
        
        run_agent_on_issue(work, access_token=tok)
        
        logger.info(
            "Successfully processed issue #%s in %s",
            work.issue_number,
            work.full_name,
        )
        
        try:
            _transition_in_progress_to_done(work, tok)
        except Exception as label_err:
            logger.exception("Failed to set greagent:done label: %s", label_err)
            
    except Exception as e:
        logger.exception(
            "Worker failed to process issue #%s in %s/%s: %s",
            issue_data.get("issue_number"),
            issue_data.get("owner"),
            issue_data.get("repo_name"),
            e,
        )
        
        try:
            work = IssueOpenedForCoder(**issue_data)
            tok = get_api_token_for_coder_issue(
                work.owner,
                work.repo_name,
                github_installation_id=work.github_installation_id,
            )
            _transition_in_progress_to_error(work, tok)
            comment_on_issue(
                owner=work.owner,
                repo=work.repo_name,
                issue_number=work.issue_number,
                token=tok,
                body=(
                    "⚠️ Sorry, I encountered an error while working on this issue:\n\n"
                    f"```\n{e}\n```"
                ),
            )
        except Exception as cleanup_err:
            logger.exception("Failed to handle error cleanup: %s", cleanup_err)
        
        raise
