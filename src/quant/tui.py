"""Read-only Textual cockpit. View/animation actions never touch trading state."""
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import time

from rich.table import Table
from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Static, Footer, TabbedContent, TabPane, DataTable, Button
from .ui_theme import palette
from .ui_charts import Plot, line_plot
from .ui_animation import Orbit

def read_db(path):
    if not Path(path).exists():
        return None
    return sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro',uri=True,timeout=.2)


def has(db,table):
    return db is not None and db.execute('SELECT 1 FROM sqlite_master WHERE name=?',(table,)).fetchone() is not None


class TerminalApp(App):
    TITLE='Crypto Research Terminal'
    CSS='''
    Screen { background: $background; color: $foreground; }
    #masthead { height: 2; padding: 0 2; color: $accent; content-align: left middle; }
    Footer { background: $surface; color: $text-muted; }
    TabbedContent { height: 1fr; }
    TabPane { padding: 0 1; }
    Tabs { background: $background; }
    Tab { color: $text-muted; background: $background; }
    Tab.-active { color: $foreground; }
    Underline > .underline--bar { color: $accent; background: $background; }
    .frame { border: solid $surface-lighten-2; border-title-color: $text-muted; padding: 0 1; }
    #stats { height: 4; margin-bottom: 1; }
    #body { height: 2fr; min-height: 12; }
    #price { width: 3fr; height: 1fr; min-height: 0; margin-right: 1; overflow: hidden; }
    #side { width: 2fr; height: 1fr; min-width: 30; }
    #execution { height: 9; }
    #animation-box { height: 1fr; min-height: 8; }
    #animation-controls { height: 1; }
    #animation-controls Button { height: 1; min-width: 3; width: 3; border: none; padding: 0; background: $surface; color: $accent; }
    #animation-label { width: 1fr; height: 1; text-align: center; color: $accent; }
    #orbit { height: 1fr; content-align: center middle; }
    #animation-hint { height: 1; text-align: center; color: $text-muted; }
    #bottom { height: 1fr; min-height: 9; margin-top: 1; }
    #equity { width: 1fr; height: 1fr; min-height: 0; margin-right: 1; overflow: hidden; }
    #fills { width: 1fr; height: 1fr; min-height: 0; }
    #research-scroll { height: 1fr; }
    #research-details { height: auto; }
    #research-account { height: auto; margin-top: 1; }
    #events { height: 1fr; }
    DataTable { background: $background; color: $foreground; }
    DataTable > .datatable--header { background: $surface; color: $text-muted; text-style: none; }
    DataTable > .datatable--cursor { background: $primary-background; }
    .narrow #body { layout: vertical; }
    .narrow #price { width: 1fr; height: 1fr; margin-right: 0; }
    .narrow #side { width: 1fr; height: 9; layout: horizontal; }
    .narrow #execution { width: 2fr; height: 9; }
    .narrow #animation-box { width: 1fr; height: 9; }
    '''
    BINDINGS=[Binding('q','quit','Quit view',priority=True),
              Binding('1','tab("trading")','Trading',priority=True),
              Binding('2','tab("research")','Research',priority=True),
              Binding('3','tab("logs")','Logs',priority=True),
              Binding('a','animation','Animation',priority=True),
              Binding('left','window(-1)','Window −',priority=True),
              Binding('right','window(1)','Window +',priority=True)]

    def __init__(self,db_path,account_path,symbol='BTC/USD',initial='trading',animation=True):
        super().__init__()
        self.db_path=db_path;self.account_path=account_path;self.symbol=symbol
        self.initial=initial;self.animate_enabled=animation;self.window_index=0
        self.last_fill=None;self.last_event=None
        self.preferences=Path(db_path).parent/'ui-preferences.json'
        self.animation_choice=0
        try:
            preferences=json.loads(self.preferences.read_text())
            self.animation_choice=int(preferences.get('animation',0))%len(Orbit.NAMES)
            selected=preferences.get('theme')
            if selected and self.get_theme(selected) is not None:self.theme=selected
        except (OSError,ValueError,TypeError):pass
        self.last_theme=self.theme

    def compose(self) -> ComposeResult:
        yield Static('CRYPTO RESEARCH TERMINAL · PAPER ONLY',id='masthead')
        with TabbedContent(initial=self.initial,id='tabs'):
            with TabPane('1 Trading',id='trading'):
                yield Static(id='stats',classes='frame')
                with Horizontal(id='body'):
                    yield Plot(id='price',classes='frame')
                    with Vertical(id='side'):
                        yield Static(id='execution',classes='frame')
                        with Vertical(id='animation-box',classes='frame'):
                            with Horizontal(id='animation-controls'):
                                yield Button('◀',id='animation-prev')
                                yield Static(Orbit.NAMES[self.animation_choice],id='animation-label')
                                yield Button('▶',id='animation-next')
                            yield Orbit(id='orbit')
                            yield Static('Decorative · A pauses',id='animation-hint')
                with Horizontal(id='bottom'):
                    yield Plot(id='equity',classes='frame')
                    yield DataTable(id='fills',classes='frame')
            with TabPane('2 Research',id='research'):
                with VerticalScroll(id='research-scroll'):
                    yield Static(id='research-details')
                    yield Static(id='research-account')
            with TabPane('3 Logs',id='logs'):
                yield DataTable(id='events',classes='frame')
        yield Footer()

    def on_mount(self):
        self.theme_changed_signal.subscribe(self,self.theme_updated)
        for key,title in [('stats','ACCOUNT / SIMULATED MONEY'),('price','BTC/USD / PRICE'),
                          ('execution','EXECUTION / ENTRY SIGNAL'),('animation-box','AMBIENT MOTION'),
                          ('equity','EQUITY / AFTER COSTS'),('fills','PAPER FILLS / UTC'),('events','MARKET EVENT JOURNAL / UTC')]:
            self.query_one('#'+key).border_title=title
        self.query_one('#equity',Plot).color='positive'
        self.query_one('#orbit',Orbit).enabled=self.animate_enabled
        self.query_one('#orbit',Orbit).variant=self.animation_choice
        self.query_one('#fills',DataTable).add_columns('UTC','SIDE','PRICE','FEE','NET')
        self.query_one('#events',DataTable).add_columns('UTC','CHANNEL','EVENT')
        self.refresh_data();self.set_interval(1,self.refresh_data)

    def save_preferences(self):
        try:
            self.preferences.parent.mkdir(parents=True,exist_ok=True)
            temporary=self.preferences.with_suffix('.tmp')
            temporary.write_text(json.dumps({'theme':self.theme,'animation':self.animation_choice})+'\n')
            temporary.replace(self.preferences)
        except OSError:
            self.notify('Could not save display preferences',severity='warning')

    def theme_updated(self,theme):
        if self.theme!=self.last_theme:
            self.last_theme=self.theme
            self.save_preferences()
        self.last_fill=None
        self.refresh_data()
        self.query_one('#price',Plot).refresh()
        self.query_one('#equity',Plot).refresh()
        self.query_one('#orbit',Orbit).refresh()

    def on_resize(self,event):
        self.screen.set_class(event.size.width<105,'narrow')
        if self.is_mounted:
            self.refresh()

    def check_action(self,action,parameters):
        if self.screen.is_modal and action in {'tab','animation','window','quit'}:
            return False
        return True

    def action_tab(self,name):self.query_one('#tabs',TabbedContent).active=name

    def action_animation(self):
        orbit=self.query_one('#orbit',Orbit);orbit.enabled=not orbit.enabled;orbit.refresh()

    def action_cycle_animation(self,delta=1):
        self.animation_choice=(self.animation_choice+delta)%len(Orbit.NAMES)
        orbit=self.query_one('#orbit',Orbit)
        orbit.variant=self.animation_choice
        self.query_one('#animation-label',Static).update(Orbit.NAMES[self.animation_choice])
        orbit.refresh()
        self.save_preferences()

    def on_button_pressed(self,event):
        if event.button.id in ('animation-prev','animation-next'):
            self.action_cycle_animation(-1 if event.button.id=='animation-prev' else 1)
            event.stop()

    def action_window(self,delta):
        self.window_index=max(0,min(2,self.window_index+delta));self.refresh_data()

    def refresh_data(self):
        colors=palette(self)
        FG=colors['fg'];MUTED=colors['muted'];CYAN=colors['accent']
        GREEN=colors['positive'];RED=colors['negative'];AMBER=colors['warning']
        source=account=None
        try:
            source=read_db(self.db_path)
            if not has(source,'quotes'):
                self.query_one('#masthead',Static).update('CRYPTO RESEARCH TERMINAL · WAITING FOR RECORDER')
                self.query_one('#execution',Static).update('Start quant collect in another terminal.\nViewer does not start workers.')
                return
            row=source.execute('SELECT session,received,bid,ask,bid_qty,ask_qty FROM quotes WHERE symbol=? ORDER BY id DESC LIMIT 1',(self.symbol,)).fetchone()
            if not row:return
            session,ts,bid,ask,bq,aq=row;now=time.time();mid=(bid+ask)/2;demo=session.startswith('demo-')
            prefix='demo-%' if demo else 'live-%';age=now-ts;fresh=0<=age<=5
            title=Text('CRYPTO RESEARCH TERMINAL',style=CYAN)
            title.append('   %s  $%s  ·  '%(self.symbol,format(mid,',.2f')),style=FG)
            title.append('SYNTHETIC' if demo else 'PAPER',style=AMBER)
            title.append('  ·  '+('FEED FRESH' if fresh else 'FEED STALE'),style=GREEN if fresh else RED)
            self.query_one('#masthead',Static).update(title)
            window=(180,900,1800)[self.window_index]
            # Time-bucketed SQL preserves last observed quote per second and all gaps.
            points=source.execute('SELECT q.received,(q.bid+q.ask)/2 FROM quotes q JOIN '
                '(SELECT MAX(id) id FROM quotes WHERE symbol=? AND session LIKE ? AND received>=? '
                'GROUP BY CAST(received AS INTEGER)) s ON q.id=s.id ORDER BY q.received',
                (self.symbol,prefix,ts-window)).fetchall()
            price=self.query_one('#price',Plot);price.points=points;price.window=window;price.markers=[]
            price.border_title='%s / PRICE / %s MIN'%(self.symbol,window//60)
            shadow_live=has(source,'shadow_health') and bool(source.execute('SELECT 1 FROM shadow_health WHERE heartbeat>=? AND heartbeat<=?',(now-4,now)).fetchone())
            workers=int(fresh)+int(shadow_live)
            account=read_db(self.account_path)
            if has(account,'model_runner'):
                from .paper import account as get_account
                a=get_account(account);c=json.loads(a['config'])
                if c['symbol']!=self.symbol or c['demo']!=demo:
                    raise ValueError('Paper account symbol or data mode does not match market view')
                heartbeat,reason,edge,estimate=account.execute('SELECT heartbeat,reason,edge_bps,forecast FROM model_runner WHERE id=1').fetchone()
                active=heartbeat is not None and 0<=now-heartbeat<3;workers+=int(active)
                # Mark holdings from the current source quote; label stale source explicitly.
                value=a['cash']+a['qty']*bid*(1-c['fee_bps']/10000)
                pnl=value-c['initial']
                stats=Table.grid(expand=True,padding=(0,2))
                stats.add_row('EQUITY','NET P&L','FEES','POSITION','WORKERS')
                stats.add_row(Text('$%.4f'%value,style=FG),Text('%+.4f'%pnl,style=GREEN if pnl>=0 else RED),
                    Text('$%.4f'%a['fees'],style=AMBER),Text('%.8f'%a['qty'] if a['qty'] else 'FLAT'),
                    Text('%s/3 ONLINE'%workers,style=GREEN if workers==3 else AMBER))
                self.query_one('#stats',Static).update(stats)
                held=max(0,now-a['entered']) if a['entered'] else 0
                detail=Text(('ACTIVE' if active else 'STOPPED / STALE')+' · '+a['status']+'\n',style=GREEN if active else AMBER)
                detail.append('Entry: '+reason+'\n',style=MUTED)
                detail.append('Estimate vs ask: '+('%+.3f bps'%edge if edge is not None else 'unavailable')+'\n')
                detail.append('Held %.1fs / 15s · $10 size\n'%held)
                detail.append('Fees %.1f bps/side · no leverage\n'%c['fee_bps'],style=AMBER)
                detail.append('Diagnostic trades · not cost-gated',style=MUTED)
                if not fresh:detail.append('\nSTALE mark: last available price',style=RED)
                self.query_one('#execution',Static).update(detail)
                equity=self.query_one('#equity',Plot)
                equity.points=account.execute('SELECT at,equity FROM paper_equity WHERE at>=? ORDER BY quote_id',(ts-window,)).fetchall()
                equity.window=window;equity.border_title='EQUITY / AFTER COSTS / %s MIN'%(window//60);equity.refresh()
                fills=account.execute('SELECT id,at,side,price,fee,net_pnl FROM paper_fills ORDER BY id DESC LIMIT 50').fetchall()
                if fills and fills[0][0]!=self.last_fill:
                    table=self.query_one('#fills',DataTable);table.clear()
                    for _,t,side,p,fee,net in fills:
                        table.add_row(datetime.fromtimestamp(t,timezone.utc).strftime('%H:%M:%S'),
                            Text(side,style=GREEN if side=='BUY' else RED),'%.2f'%p,'%.4f'%fee,
                            Text('%+.4f'%net,style=GREEN if net>=0 else RED) if net is not None else '—')
                    self.last_fill=fills[0][0]
                price.markers=[(t,p,side) for _,t,side,p,_,_ in fills]
            else:
                self.query_one('#stats',Static).update('No model-paper account yet · %s/3 workers online'%workers)
                self.query_one('#execution',Static).update('Start quant model-paper separately.\nNo real orders.\nResearch can continue without trades.')
            price.refresh()
            tab=self.query_one('#tabs',TabbedContent).active
            if tab=='research':
                from .microprice import panel as research_panel
                from .paper import panel as old_panel
                research=research_panel(source,self.symbol,demo);research.border_style=colors['accent']
                self.query_one('#research-details',Static).update(research)
                archived=old_panel(source,bid,now,self.symbol,demo);archived.border_style=colors['muted']
                self.query_one('#research-account',Static).update(archived)
            elif tab=='logs':
                events=source.execute('SELECT id,received,channel,payload FROM events ORDER BY id DESC LIMIT 100').fetchall()
                if events and events[0][0]!=self.last_event:
                    table=self.query_one('#events',DataTable);table.clear()
                    for _,t,ch,p in events:
                        payload=json.loads(p)
                        summary=payload.get('error') or ('%s records'%len(payload['data']) if 'data' in payload else p[:140])
                        table.add_row(datetime.fromtimestamp(t,timezone.utc).strftime('%H:%M:%S'),ch,Text(str(summary)))
                    self.last_event=events[0][0]
        except (sqlite3.Error,ValueError) as exc:
            self.query_one('#masthead',Static).update(Text('DATA UNAVAILABLE · '+str(exc),style=AMBER))
        finally:
            if account:account.close()
            if source:source.close()
