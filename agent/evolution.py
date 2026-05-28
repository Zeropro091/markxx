import subprocess
import time
import copy
from pathlib import Path
from core.logger import get_logger
from core.memory import Memory
from core.llm import LLMClient
from agent.cli_planner import CLIPlanner

log = get_logger("evolution")

class SelfEvolver:
    def __init__(self, planner, working_dir: str):
        self.planner = planner
        self.working_dir = Path(working_dir).resolve()

    def run_evolution(self, evolution_prompt: str) -> str:
        """Runs the evolution cycle on a new git branch, runs tests, and rolls back if failed."""
        # 1. Check if git is installed and repo is clean
        try:
            # We want to see if the directory is a git repo
            subprocess.run(["git", "rev-parse", "--is-inside-work-tree"], capture_output=True, text=True, check=True)
            status = subprocess.check_output(["git", "status", "--porcelain"], text=True)
            stashed = False
            if status.strip():
                log.info("Stashing dirty working tree before evolution...")
                subprocess.check_call(["git", "stash"])
                stashed = True
        except (subprocess.CalledProcessError, FileNotFoundError):
            return "❌ Error: Self-evolution requires a Git repository. Please initialize a git repo first."

        # Get current branch
        try:
            original_branch = subprocess.check_output(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"], text=True
            ).strip()
        except subprocess.CalledProcessError as e:
            return f"❌ Git error: {e}"

        # Create new branch
        timestamp = time.strftime("%Y%m%d-%H%M%S")
        evolve_branch = f"mark-evolve-{timestamp}"
        log.info(f"Creating evolution branch: {evolve_branch}")
        try:
            subprocess.check_call(["git", "checkout", "-b", evolve_branch])
        except subprocess.CalledProcessError as e:
            if stashed:
                subprocess.call(["git", "stash", "pop"])
            return f"❌ Failed to create branch: {e}"

        # 2. Run the agent to execute the self-rewrite/improvement task!
        # Prompt explicitly instructs it to modify the codebase
        task_prompt = (
            f"You are modifying YOUR OWN codebase to evolve/add a feature. The goal is: {evolution_prompt}\n"
            f"Only edit files inside the project structure (like agent/, core/, config/, tui.py, markcli.py).\n"
            f"After rewriting, verify that your changes compile and run without errors."
        )
        
        success = False
        response = ""
        temp_db_path = self.working_dir / "memory" / f"evolution_temp_{timestamp}.db"
        
        try:
            log.info("Instantiating isolated secondary agent for self-evolution...")
            
            # Setup isolated Memory db
            temp_memory = Memory(str(temp_db_path))
            
            # Setup isolated LLMClient and CLIPlanner
            child_settings = copy.deepcopy(self.planner.settings)
            child_settings.cli_enable_self_evolution = False  # Prevent nested evolution
            
            all_keys = self.planner.settings.get_all_keys()
            api_key = all_keys[0] if all_keys else ""
            extra_keys = all_keys[1:] if len(all_keys) > 1 else []
            
            child_llm_client = LLMClient(
                api_key=api_key,
                model=child_settings.gemini_model,
                system_prompt="",
                extra_keys=extra_keys,
                temperature=child_settings.llm_temperature,
                max_tokens=None,
            )
            
            second_planner = CLIPlanner(
                child_llm_client,
                temp_memory,
                working_dir=str(self.working_dir),
                mode=self.planner.interceptor.mode,
                budget_usd=self.planner.budget.max_budget_usd,
                dry_run=self.planner.dry_runner.active,
                settings=child_settings
            )
            
            # Process prompt
            response = second_planner.process(task_prompt, str(self.working_dir))
            
            # 3. Run verification tests!
            # We compile/verify imports of major files as a sanity test.
            log.info("Running verification test...")
            python_path = str(self.working_dir / "venv" / "Scripts" / "python.exe")
            if not Path(python_path).exists():
                python_path = "python"
                
            test_proc = subprocess.run(
                [python_path, "-c", "import tui; import markcli; import agent.cli_planner; print('Sanity check: OK')"],
                capture_output=True, text=True, timeout=15
            )
            
            if test_proc.returncode == 0:
                success = True
                log.info("Verification passed!")
            else:
                log.warning(f"Verification failed: {test_proc.stderr}")
                response += f"\n\nVerification failed with exit code {test_proc.returncode}:\n{test_proc.stderr}"
        except Exception as e:
            log.error(f"Evolution failed: {e}")
            response += f"\n\nEvolution exception: {e}"
        finally:
            # Clean up isolated memory DB file
            try:
                if temp_db_path.exists():
                    temp_db_path.unlink()
            except Exception as clean_err:
                log.warning(f"Could not delete temporary evolution database {temp_db_path}: {clean_err}")

        # 4. Handle success vs failure (Rollback)
        if success:
            try:
                # Commit the evolution changes
                subprocess.check_call(["git", "add", "."])
                subprocess.check_call(["git", "commit", "-m", f"feat(evolve): {evolution_prompt}"])
                result_msg = (
                    f"🚀 **Evolution Success!**\n"
                    f"Code rewritten and verified on branch `{evolve_branch}`.\n"
                    f"You can review the changes and merge them: `git diff {original_branch} {evolve_branch}`\n\n"
                    f"Agent reasoning/response:\n{response}"
                )
            except Exception as commit_err:
                result_msg = f"❌ Evolution completed but commit failed: {commit_err}"
        else:
            # Rollback: Switch back to original branch and delete the evolution branch
            log.warning("Evolution failed or tests did not pass. Rolling back...")
            try:
                subprocess.check_call(["git", "checkout", original_branch])
                subprocess.check_call(["git", "branch", "-D", evolve_branch])
                if stashed:
                    subprocess.call(["git", "stash", "pop"])
                result_msg = (
                    f"⚠️ **Evolution Failed & Rolled Back**\n"
                    f"The code modifications failed verification tests. "
                    f"Rolled back cleanly to original branch `{original_branch}`. The experimental branch was deleted.\n\n"
                    f"Details:\n{response}"
                )
            except Exception as rollback_err:
                result_msg = f"❌ Fatal rollback error: {rollback_err}. You may be stuck on branch `{evolve_branch}`."

        return result_msg
