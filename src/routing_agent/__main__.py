"""Entry point for `python -m routing_agent` — delegates to the adapter."""

from routing_agent.adapter import main

if __name__ == "__main__":
    raise SystemExit(main())
