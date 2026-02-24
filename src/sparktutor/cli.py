"""CLI entry point for SparkTutor."""

import click


@click.group(invoke_without_command=True)
@click.option("--dry-run", is_flag=True, help="Force dry-run mode (no Spark execution)")
@click.pass_context
def main(ctx: click.Context, dry_run: bool) -> None:
    """SparkTutor — Interactive Spark 4.1 learning environment."""
    ctx.ensure_object(dict)
    ctx.obj["dry_run"] = dry_run
    if ctx.invoked_subcommand is None:
        ctx.invoke(launch)


@main.command()
@click.pass_context
def launch(ctx: click.Context) -> None:
    """Launch the interactive learning environment."""
    from sparktutor.app.main_app import SparkTutorApp

    app = SparkTutorApp(force_dry_run=ctx.obj.get("dry_run", False))
    app.run()


@main.command()
def courses() -> None:
    """List available courses."""
    from sparktutor.courses.registry import CourseRegistry

    registry = CourseRegistry()
    for course in registry.list_courses():
        click.echo(f"  {course.id}: {course.title} ({len(course.lessons)} lessons)")


@main.command()
def status() -> None:
    """Show execution environment status."""
    import asyncio

    from sparktutor.engine.executor import Executor

    async def _check():
        executor = Executor()
        mode = await executor.detect_mode()
        click.echo(f"Execution mode: {mode.value}")

    asyncio.run(_check())
