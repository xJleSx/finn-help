import secrets

import typer

from src.cli.commands import console, security_app
from src.core.crypto import encrypt


@security_app.command()
def generate_key() -> None:
    """Generate a new encryption key for .env"""
    from cryptography.fernet import Fernet

    key = Fernet.generate_key().decode()
    console.print(f"[bold green]ENCRYPTION_KEY={key}[/bold green]")
    console.print("\nAdd this to your .env file to enable token encryption at rest.")


@security_app.command()
def encrypt_value(
    value: str = typer.Argument(..., help="The value to encrypt"),
) -> None:
    """Encrypt a sensitive value (API key, token, etc.)"""
    encrypted = encrypt(value)
    if encrypted == value and not value.startswith("gAAAAA"):
        console.print("[red]Encryption failed or ENCRYPTION_KEY not set[/red]")
        raise typer.Exit(1)
    console.print(f"[green]Encrypted:[/green] {encrypted}")


@security_app.command()
def generate_jwt_secret() -> None:
    """Generate a secure JWT secret for .env"""
    secret = secrets.token_urlsafe(48)
    console.print(f"[bold green]JWT_SECRET={secret}[/bold green]")


@security_app.command()
def generate_jwt_refresh_secret() -> None:
    """Generate a secure JWT refresh secret for .env"""
    secret = secrets.token_urlsafe(48)
    console.print(f"[bold green]JWT_REFRESH_SECRET={secret}[/bold green]")


@security_app.command()
def check_env() -> None:
    """Check security settings and report issues"""
    import os
    from pathlib import Path

    issues: list[str] = []
    ok_count = 0

    env_path = Path(".env")
    if not env_path.exists():
        issues.append(".env file not found")
    else:
        ok_count += 1

    jwt = os.environ.get("JWT_SECRET", "")
    if not jwt:
        issues.append("JWT_SECRET is not set — sessions will be invalidated on restart")
    elif jwt == "_DEFAULT_JWT":
        issues.append("JWT_SECRET is using the default value — set a custom secret")
    else:
        ok_count += 1

    enc_key = os.environ.get("ENCRYPTION_KEY", "")
    if not enc_key:
        issues.append("ENCRYPTION_KEY is not set — tokens stored in plaintext")
    else:
        ok_count += 1

    db_url = os.environ.get("DATABASE_URL", "")
    if "finn:finn" in db_url:
        issues.append("DATABASE_URL contains default credentials (finn:finn)")
    else:
        ok_count += 1

    if issues:
        console.print("[yellow]Security issues found:[/yellow]")
        for issue in issues:
            console.print(f"  [red]![/red] {issue}")
    else:
        console.print("[bold green]No security issues found![/bold green]")

    console.print(f"\n[dim]Checks passed: {ok_count}/{ok_count + len(issues)}[/dim]")
