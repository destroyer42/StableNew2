import os, time, tkinter as tk
from src.gui.main_window import StableNewGUI, enable_gui_test_mode
from src.gui.state import GUIState, CancellationError

os.environ['STABLENEW_GUI_TEST_MODE'] = '1'
os.environ['STABLENEW_NO_WEBUI'] = '1'
enable_gui_test_mode()
root = tk.Tk(); root.withdraw()
app = StableNewGUI(root)
app.api_connected = True
app.controller._sync_cleanup = True
app.prompt_text = tk.Text(root)
app.prompt_text.insert('1.0', 'test prompt')
app.enable_img2img_var = tk.BooleanVar(value=True)
app.enable_upscale_var = tk.BooleanVar(value=True)
app.batch_size_var = tk.IntVar(value=1)
app.run_name_var = tk.StringVar(value='')
app.progress_message_var = tk.StringVar(value='Ready')

class CancelAwarePipeline:
    def run_full_pipeline(self, *args, **kwargs):
        cancel_token = kwargs.get('cancel_token')
        while not cancel_token.is_cancelled():
            time.sleep(0.01)
        raise CancellationError('cancelled')

app.client = object()
app.pipeline = CancelAwarePipeline()
print('starting pipeline', flush=True)
app._run_pipeline()
print('state after start', app.state_manager.current, flush=True)
print('stopping pipeline', flush=True)
app.controller.stop_pipeline()
print('event set', app.controller.lifecycle_event.wait(timeout=1.0), flush=True)
for _ in range(5):
    try:
        root.update()
    except tk.TclError:
        break
    time.sleep(0.01)
print('final state', app.state_manager.current, flush=True)
print('progress message', app.progress_message_var.get(), flush=True)
root.destroy()
import os, time, tkinter as tk
from src.gui.main_window import StableNewGUI, enable_gui_test_mode
from src.gui.state import GUIState, CancellationError

os.environ['STABLENEW_GUI_TEST_MODE'] = '1'
os.environ['STABLENEW_NO_WEBUI'] = '1'
enable_gui_test_mode()
root = tk.Tk(); root.withdraw()
app = StableNewGUI(root)
app.api_connected = True
app.controller._sync_cleanup = True
app.prompt_text = tk.Text(root)
app.prompt_text.insert('1.0', 'test prompt')
app.enable_img2img_var = tk.BooleanVar(value=True)
app.enable_upscale_var = tk.BooleanVar(value=True)
app.batch_size_var = tk.IntVar(value=1)
app.run_name_var = tk.StringVar(value='')
app.progress_message_var = tk.StringVar(value='Ready')

class CancelAwarePipeline:
    def run_full_pipeline(self, *args, **kwargs):
        cancel_token = kwargs.get('cancel_token')
        while not cancel_token.is_cancelled():
            time.sleep(0.01)
        raise CancellationError('cancelled')

app.client = object()
app.pipeline = CancelAwarePipeline()
print('starting pipeline', flush=True)
app._run_pipeline()
print('state after start', app.state_manager.current, flush=True)
print('stopping pipeline', flush=True)
app.controller.stop_pipeline()
print('event set', app.controller.lifecycle_event.wait(timeout=1.0), flush=True)
for _ in range(5):
    try:
        root.update()
    except tk.TclError:
        break
    time.sleep(0.01)
print('final state', app.state_manager.current, flush=True)
print('progress message', app.progress_message_var.get(), flush=True)
root.destroy()
