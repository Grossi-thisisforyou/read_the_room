"""An open question from the engine (ask, no options) must reach the screen."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'n900'))
import agent as A  # noqa: E402


def make():
    conf = dict(A.DEFAULTS)
    conf.update({'camera': 0, 'mic': 0, 'keep_awake': 0})
    return A.Agent(conf, fake=True, sysfs_root='/nonexistent')


def test_open_question_is_shown_as_text():
    a = make()
    a.handle({'type': 'phone', 'ts': 0, 'data': {'ask': 'What do you never tell anyone?'}})
    snap = a.ui_snapshot()
    assert snap['text'] == 'What do you never tell anyone?'
    assert snap['prompt'] is None


def test_two_option_prompt_is_still_a_prompt():
    a = make()
    a.handle({'type': 'phone', 'ts': 0, 'data': {'prompt_id': 'closer', 'ask': 'look closer?',
                                                 'options': ['look closer', 'look away']}})
    assert a.ui_snapshot()['prompt']['options'] == ['look closer', 'look away']
