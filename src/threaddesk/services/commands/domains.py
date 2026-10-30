"""Built-in domain registrations; no alternate module or data store."""
def specifications():
    from threaddesk.services.commands.context import specifications as context
    from threaddesk.services.commands.graph import specifications as graph
    from threaddesk.services.commands.operations import specifications as operations
    from threaddesk.services.commands.owner_search import specifications as owner_search
    from threaddesk.services.commands.library_compat import specifications as library_compat
    from threaddesk.services.commands.whiteboards import specifications as whiteboards
    from threaddesk.services.commands.prompt_history import specifications as prompt_history
    from threaddesk.services.commands.authority import specifications as authority
    yield from prompt_history()
    yield from authority()
    yield from whiteboards()
    yield from context()
    yield from graph()
    yield from operations()
    yield from owner_search()
    yield from library_compat()
