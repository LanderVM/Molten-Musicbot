import subprocess
import sys


def run_command(command):
    """Run a command and print the output."""
    try:
        result = subprocess.run(
            command,
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        print(f"Command '{' '.join(command)}' ran successfully.")
        print(result.stdout)
    except subprocess.CalledProcessError as e:
        print(f"Error running command '{' '.join(command)}':")
        print(e.stderr)
        sys.exit(1)


if __name__ == "__main__":
    run_command(["python", "-m", "ruff", "check", ".", "--fix"])
    run_command(["python", "-m", "isort", "."])
    run_command(["python", "-m", "black", "."])
