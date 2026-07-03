def fix_readline():
    try:
        import readline
        readline.parse_and_bind('set bind-tty-special-chars off')
        readline.parse_and_bind('set input-meta on')
        readline.parse_and_bind('set output-meta on')
        readline.parse_and_bind('set convert-meta off')
    except ImportError:
        pass