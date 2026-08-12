"""Restate workflow endpoint — ready to deploy on Render.

Serve locally:   hypercorn --bind 0.0.0.0:9080 app:app
On Render:       hypercorn --bind 0.0.0.0:$PORT app:app
"""
from datetime import timedelta

import restate
from restate import Workflow, WorkflowContext, WorkflowSharedContext

# --- A simple, real workflow: a user signup with email verification ---------
signup = Workflow("SignupWorkflow")


async def _send_email(user_id: str) -> str:
    # Pretend to call an email provider. In real life, put your SDK call here.
    print(f"[send_email] verification email sent to {user_id}")
    return f"sent:{user_id}"


@signup.main()
async def run(ctx: WorkflowContext, user_id: str) -> str:
    # ctx.run() makes the side effect durable: retried on failure, never
    # re-executed once it succeeds (survives crashes/restarts).
    await ctx.run("send verification email", _send_email, args=(user_id,))

    # Durably wait (up to 24h) for the user to click the link. This survives
    # restarts — Restate persists the promise, not a live process.
    click = ctx.promise("email_verified")
    try:
        verified = await click.value()
    except restate.TerminalError:
        verified = False

    if not verified:
        return f"signup_expired:{user_id}"

    return f"signup_complete:{user_id}"


@signup.handler()
async def verify(ctx: WorkflowSharedContext, secret: str) -> str:
    # Called from the outside (e.g. the email link) to unblock the main handler.
    await ctx.promise("email_verified").resolve(True)
    return "ok"


# ASGI app that Restate connects to. request_response = safe behind Render's
# proxy (and required for AWS Lambda, which can't do bidi streaming).
app = restate.app(services=[signup], protocol="request_response")

# --- AWS Lambda entry point --------------------------------------------------
# Same `app`, wrapped as a Lambda handler. Set the Lambda handler to
# "app.handler". Harmless when running under hypercorn (Render).
from restate.aws_lambda import wrap_asgi_as_lambda_handler  # noqa: E402

handler = wrap_asgi_as_lambda_handler(app)
