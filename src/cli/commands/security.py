import secrets
from typing import Optional

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

    env_path = Path(__file__).resolve().parent.parent.parent / ".env"
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


@security_app.command(name="credential-set")
def credential_set(
    broker: str = typer.Argument(..., help="Broker name (tbank, bcs, finam, alor, openapi)"),
    token: str = typer.Argument(..., help="API token to encrypt and store"),
    user_id: int = typer.Option(0, "--user", "-u", help="User ID"),
) -> None:
    """Encrypt and store a broker API token in the database."""
    from src.core.credential_store import set_broker_token
    from src.db.connection import get_session

    db = get_session()
    try:
        set_broker_token(user_id, broker, token, db)
        console.print(f"[green]Token for [bold]{broker}[/bold] stored encrypted (user={user_id})[/green]")
    except Exception as e:
        console.print(f"[red]Failed to store credential: {e}[/red]")
        raise typer.Exit(1)
    finally:
        db.close()


@security_app.command(name="credential-delete")
def credential_delete(
    broker: str = typer.Argument(..., help="Broker name"),
    user_id: int = typer.Option(0, "--user", "-u", help="User ID"),
) -> None:
    """Delete a stored broker credential from the database."""
    from src.core.credential_store import delete_broker_token
    from src.db.connection import get_session

    db = get_session()
    try:
        if delete_broker_token(user_id, broker, db):
            console.print(f"[green]Credential for [bold]{broker}[/bold] deleted[/green]")
        else:
            console.print(f"[yellow]No credential found for {broker} (user={user_id})[/yellow]")
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)
    finally:
        db.close()


@security_app.command(name="credential-list")
def credential_list(
    user_id: int = typer.Option(0, "--user", "-u", help="User ID"),
) -> None:
    """List stored broker credentials (tokens not shown)."""
    from src.core.credential_store import list_broker_tokens
    from src.db.connection import get_session

    db = get_session()
    try:
        creds = list_broker_tokens(user_id, db)
        if not creds:
            console.print("[yellow]No broker credentials stored[/yellow]")
        else:
            console.print(f"[bold]Broker credentials (user={user_id}):[/bold]")
            for c in creds:
                status = "[green]active[/green]" if c["is_active"] else "[dim]inactive[/dim]"
                console.print(f"  {c['broker_name']:10s} {status}  [dim]({c['updated_at'] or 'never'})[/dim]")
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)
    finally:
        db.close()


@security_app.command(name="credential-test")
def credential_test(
    broker: str = typer.Argument(..., help="Broker name"),
    user_id: int = typer.Option(0, "--user", "-u", help="User ID"),
) -> None:
    """Test that a stored credential decrypts and resolves correctly."""
    from src.core.credential_store import get_broker_token
    from src.db.connection import get_session

    db = get_session()
    try:
        token = get_broker_token(user_id, broker, db)
        if token:
            masked = token[:6] + "…" + token[-4:] if len(token) > 12 else "…"
            console.print(f"[green]Token for [bold]{broker}[/bold] resolves: {masked}[/green]")
        else:
            console.print(f"[red]No token resolves for [bold]{broker}[/bold] (user={user_id})[/red]")
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)
    finally:
        db.close()
