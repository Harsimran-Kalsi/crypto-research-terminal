import tempfile
from pathlib import Path
import unittest
from textual.widgets import TabbedContent, Input
from quant.tui import TerminalApp,Orbit,line_plot


class TerminalTests(unittest.IsolatedAsyncioTestCase):
    async def test_view_navigation_animation_and_resize_do_not_create_databases(self):
        with tempfile.TemporaryDirectory() as d:
            market=Path(d)/'missing-market.db';account=Path(d)/'missing-account.db'
            app=TerminalApp(str(market),str(account),animation=False)
            async with app.run_test(size=(160,48)) as pilot:
                await pilot.pause()
                self.assertFalse(app.query_one('#orbit',Orbit).enabled)
                await pilot.press('2');await pilot.pause()
                self.assertEqual(app.query_one('#tabs',TabbedContent).active,'research')
                await pilot.press('3');await pilot.pause()
                self.assertEqual(app.query_one('#tabs',TabbedContent).active,'logs')
                await pilot.press('1','a','right');await pilot.pause()
                self.assertTrue(app.query_one('#orbit',Orbit).enabled)
                self.assertEqual(app.window_index,1)
                await pilot.resize_terminal(95,42);await pilot.pause()
                self.assertTrue(app.screen.has_class('narrow'))
            self.assertFalse(market.exists())
            self.assertFalse(account.exists())

    async def test_palette_typing_and_selected_theme_survive_restart(self):
        with tempfile.TemporaryDirectory() as d:
            market=str(Path(d)/'market.db');account=str(Path(d)/'account.db')
            app=TerminalApp(market,account)
            async with app.run_test(size=(140,44)) as pilot:
                await pilot.pause()
                await pilot.press('ctrl+p');await pilot.pause()
                await pilot.press(*list('theme'));await pilot.pause()
                self.assertEqual(app.screen.query_one(Input).value,'theme')
                await pilot.press('escape');await pilot.pause()
                dark_background=app.screen.styles.background
                app.theme='textual-light';await pilot.pause()
                self.assertNotEqual(app.screen.styles.background,dark_background)
                self.assertEqual(app.theme,'textual-light')
            reopened=TerminalApp(market,account)
            self.assertEqual(reopened.theme,'textual-light')
            self.assertFalse(Path(market).exists())
            self.assertFalse(Path(account).exists())

    async def test_animation_buttons_right_click_and_saved_selection(self):
        with tempfile.TemporaryDirectory() as d:
            market=str(Path(d)/'market.db');account=str(Path(d)/'account.db')
            app=TerminalApp(market,account)
            async with app.run_test(size=(160,48)) as pilot:
                await pilot.pause()
                self.assertGreater(app.query_one('#animation-box').size.height,12)
                self.assertEqual(app.animation_choice,0)
                await pilot.click('#animation-next');await pilot.pause()
                self.assertEqual(app.animation_choice,1)
                await pilot.click('#animation-next');await pilot.pause()
                self.assertEqual(app.animation_choice,2)
                await pilot.click('#orbit',offset=(3,2),button=3);await pilot.pause()
                self.assertEqual(app.animation_choice,0)
                await pilot.click('#animation-prev');await pilot.pause()
                self.assertEqual(app.animation_choice,2)
                self.assertEqual(app.query_one('#orbit',Orbit).variant,2)
            restored=TerminalApp(market,account)
            self.assertEqual(restored.animation_choice,2)
            self.assertFalse(Path(market).exists())
            self.assertFalse(Path(account).exists())

    def test_chart_marks_real_trades_without_connecting_long_gap(self):
        rendered=line_plot([(0,100),(180,101)],[(180,101,'SELL')],20,4,180)
        self.assertIn('S',rendered.plain)
        self.assertLess(sum(0x2800<ord(c)<=0x28ff for c in rendered.plain),4)
