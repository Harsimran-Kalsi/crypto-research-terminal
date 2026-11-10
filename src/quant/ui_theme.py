"""Resolve semantic colors from the selected Textual theme."""
from textual.color import Color

BG='#10151c'; FG='#d4dce6'; MUTED='#8190a3'; CYAN='#77c7d6'; GREEN='#7ac69c'; RED='#df8d8d'; AMBER='#d8b77c'


def palette(app):
    variables=app.get_css_variables()
    def value(name,fallback):
        try:
            raw=variables.get(name,fallback)
            if raw.startswith('auto '):
                alpha=float(raw.split()[1].rstrip('%'))/100
                return Color.parse(variables['foreground']).blend(Color.parse(variables['background']),1-alpha).hex
            return Color.parse(raw).hex
        except Exception:return fallback
    return dict(fg=value('foreground',FG),muted=value('text-muted',MUTED),
                accent=value('accent',CYAN),positive=value('success',GREEN),
                negative=value('error',RED),warning=value('warning',AMBER))
