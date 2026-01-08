import sys
import json
import logging
import random
from abc import abstractmethod
import glob
import time
import os
from lxml import etree as ET
from droidbot.device_state import DeviceState

from .input_event import InputEvent, KeyEvent, IntentEvent, TouchEvent, ManualEvent, SetTextEvent, KillAppEvent
from .utg import UTG
from .utils import generate_html_report
from .UIMatch.Matcher import Matcher
from .UIMatch.Logger import get_logger
from .UIMatch.utils import read_image, compute_ssim

# Max number of restarts
MAX_NUM_RESTARTS = 5
# Max number of steps outside the app
MAX_NUM_STEPS_OUTSIDE = 5
MAX_NUM_STEPS_OUTSIDE_KILL = 10
# Max number of replay tries
MAX_REPLY_TRIES = 5

# Some input event flags
EVENT_FLAG_STARTED = "+started"
EVENT_FLAG_START_APP = "+start_app"
EVENT_FLAG_STOP_APP = "+stop_app"
EVENT_FLAG_EXPLORE = "+explore"
EVENT_FLAG_NAVIGATE = "+navigate"
EVENT_FLAG_TOUCH = "+touch"

# Policy taxanomy
RANDOM_EXPLORATION = "random_exploration"
MATCHING = "matching"
GROUND_TRUTH = "ground_truth"
POLICY_NAIVE_DFS = "dfs_naive"
POLICY_GREEDY_DFS = "dfs_greedy"
POLICY_NAIVE_BFS = "bfs_naive"
POLICY_GREEDY_BFS = "bfs_greedy"
POLICY_REPLAY = "replay"
POLICY_MANUAL = "manual"
POLICY_MONKEY = "monkey"
POLICY_NONE = "none"
POLICY_MEMORY_GUIDED = "memory_guided"  # implemented in input_policy2
POLICY_LLM_GUIDED = "llm_guided"  # implemented in input_policy3


class InputInterruptedException(Exception):
    pass


class InputPolicy(object):
    """
    This class is responsible for generating events to stimulate more app behaviour
    It should call AppEventManager.send_event method continuously
    """

    def __init__(self, device, app):
        self.logger = logging.getLogger(self.__class__.__name__)
        self.device = device
        self.app = app
        self.action_count = 0
        self.master = None
        self.input_manager=None

    def start(self, input_manager):
        """
        start producing events
        :param input_manager: instance of InputManager
        """
        self.action_count = 0
        self.input_manager = input_manager
        while input_manager.enabled and self.action_count < input_manager.event_count:
            try:
                # # make sure the first event is go to HOME screen
                # # the second event is to start the app
                # if self.action_count == 0 and self.master is None:
                #     event = KeyEvent(name="HOME")
                # elif self.action_count == 1 and self.master is None:
                #     event = IntentEvent(self.app.get_start_intent())
                if self.action_count == 0 and self.master is None:
                    event = KillAppEvent(app=self.app)
                    self.device.install_files(self.app.get_package_name())
                else:
                    # 在应用启动后立即尝试跳过欢迎界面
                    if self.action_count == 2:
                        self.logger.info("App started,: attempting to skip welcome screen...")
                        self.device.skip_welcome(self.app.get_package_name())
                    event = self.generate_event()
                input_manager.add_event(event, self.action_count)
            except KeyboardInterrupt:
                break
            except InputInterruptedException as e:
                self.logger.warning("stop sending events: %s" % e)
                break
            # except RuntimeError as e:
            #     self.logger.warning(e.message)
            #     break
            except Exception as e:
                self.logger.warning("exception during sending events: %s" % e)
                import traceback
                traceback.print_exc()
                continue
            self.action_count += 1

    @abstractmethod
    def generate_event(self):
        """
        generate an event
        @return:
        """
        pass


class NoneInputPolicy(InputPolicy):
    """
    do not send any event
    """

    def __init__(self, device, app):
        super(NoneInputPolicy, self).__init__(device, app)

    def generate_event(self):
        """
        generate an event
        @return:
        """
        return None


class UtgBasedInputPolicy(InputPolicy):
    """
    state-based input policy
    """

    def __init__(self, device, app, random_input):
        super(UtgBasedInputPolicy, self).__init__(device, app)
        self.random_input = random_input
        self.script = None
        self.master = None
        self.script_events = []
        self.last_event = None
        self.last_state = None
        self.current_state = None
        self.utg = UTG(device=device, app=app, random_input=random_input)
        self.script_event_idx = 0
        if self.device.humanoid is not None:
            self.humanoid_view_trees = []
            self.humanoid_events = []

    def generate_event(self):
        """
        generate an event
        @return:
        """

        # Get current device state
        self.current_state = self.device.get_current_state()
        if self.current_state is None:
            time.sleep(5)
            return KeyEvent(name="BACK")

        # self.__update_utg()
        self.current_state.tag = str(self.action_count) # 按action_count命名，方便后续查看
        self.current_state.save2dir()

        # update last view trees for humanoid
        if self.device.humanoid is not None:
            self.humanoid_view_trees = self.humanoid_view_trees + [self.current_state.view_tree]
            if len(self.humanoid_view_trees) > 4:
                self.humanoid_view_trees = self.humanoid_view_trees[1:]

        event = None

        # if the previous operation is not finished, continue
        if len(self.script_events) > self.script_event_idx:
            event = self.script_events[self.script_event_idx].get_transformed_event(self)
            self.script_event_idx += 1

        # First try matching a state defined in the script
        if event is None and self.script is not None:
            operation = self.script.get_operation_based_on_state(self.current_state)
            if operation is not None:
                self.script_events = operation.events
                # restart script
                event = self.script_events[0].get_transformed_event(self)
                self.script_event_idx = 1

        if event is None:
            event = self.generate_event_based_on_utg()

        # update last events for humanoid
        if self.device.humanoid is not None:
            self.humanoid_events = self.humanoid_events + [event]
            if len(self.humanoid_events) > 3:
                self.humanoid_events = self.humanoid_events[1:]

        self.last_state = self.current_state
        self.last_event = event
        return event

    def __update_utg(self):
        self.utg.add_transition(self.last_event, self.last_state, self.current_state)

    @abstractmethod
    def generate_event_based_on_utg(self):
        """
        generate an event based on UTG
        :return: InputEvent
        """
        pass


class UtgNaiveSearchPolicy(UtgBasedInputPolicy):
    """
    depth-first strategy to explore UFG (old)
    """

    def __init__(self, device, app, random_input, search_method):
        super(UtgNaiveSearchPolicy, self).__init__(device, app, random_input)
        self.logger = logging.getLogger(self.__class__.__name__)

        self.explored_views = set()
        self.state_transitions = set()
        self.search_method = search_method

        self.last_event_flag = ""
        self.last_event_str = None
        self.last_state = None

        self.preferred_buttons = ["yes", "ok", "activate", "detail", "more", "access",
                                  "allow", "check", "agree", "try", "go", "next"]

    def generate_event_based_on_utg(self):
        """
        generate an event based on current device state
        note: ensure these fields are properly maintained in each transaction:
          last_event_flag, last_touched_view, last_state, exploited_views, state_transitions
        @return: InputEvent
        """
        self.save_state_transition(self.last_event_str, self.last_state, self.current_state)

        if self.device.is_foreground(self.app):
            # the app is in foreground, clear last_event_flag
            self.last_event_flag = EVENT_FLAG_STARTED
        else:
            number_of_starts = self.last_event_flag.count(EVENT_FLAG_START_APP)
            # If we have tried too many times but the app is still not started, stop DroidBot
            if number_of_starts > MAX_NUM_RESTARTS:
                raise InputInterruptedException("The app cannot be started.")

            # if app is not started, try start it
            if self.last_event_flag.endswith(EVENT_FLAG_START_APP):
                # It seems the app stuck at some state, and cannot be started
                # just pass to let viewclient deal with this case
                self.logger.info("The app had been restarted %d times.", number_of_starts)
                self.logger.info("Trying to restart app...")
                pass
            else:
                start_app_intent = self.app.get_start_intent()

                self.last_event_flag += EVENT_FLAG_START_APP
                self.last_event_str = EVENT_FLAG_START_APP
                return IntentEvent(start_app_intent)

        # select a view to click
        view_to_touch = self.select_a_view(self.current_state)

        # if no view can be selected, restart the app
        if view_to_touch is None:
            stop_app_intent = self.app.get_stop_intent()
            self.last_event_flag += EVENT_FLAG_STOP_APP
            self.last_event_str = EVENT_FLAG_STOP_APP
            return IntentEvent(stop_app_intent)

        view_to_touch_str = view_to_touch['view_str']
        if view_to_touch_str.startswith('BACK'):
            result = KeyEvent('BACK')
        else:
            result = TouchEvent(view=view_to_touch)

        self.last_event_flag += EVENT_FLAG_TOUCH
        self.last_event_str = view_to_touch_str
        self.save_explored_view(self.current_state, self.last_event_str)
        return result

    def select_a_view(self, state):
        """
        select a view in the view list of given state, let droidbot touch it
        @param state: DeviceState
        @return:
        """
        views = []
        for view in state.views:
            if view['enabled'] and len(view['children']) == 0:
                views.append(view)

        if self.random_input:
            random.shuffle(views)

        # add a "BACK" view, consider go back first/last according to search policy
        mock_view_back = {'view_str': 'BACK_%s' % state.foreground_activity,
                          'text': 'BACK_%s' % state.foreground_activity}
        if self.search_method == POLICY_NAIVE_DFS:
            views.append(mock_view_back)
        elif self.search_method == POLICY_NAIVE_BFS:
            views.insert(0, mock_view_back)

        # first try to find a preferable view
        for view in views:
            view_text = view['text'] if view['text'] is not None else ''
            view_text = view_text.lower().strip()
            if view_text in self.preferred_buttons \
                    and (state.foreground_activity, view['view_str']) not in self.explored_views:
                self.logger.info("selected an preferred view: %s" % view['view_str'])
                return view

        # try to find a un-clicked view
        for view in views:
            if (state.foreground_activity, view['view_str']) not in self.explored_views:
                self.logger.info("selected an un-clicked view: %s" % view['view_str'])
                return view

        # if all enabled views have been clicked, try jump to another activity by clicking one of state transitions
        if self.random_input:
            random.shuffle(views)
        transition_views = {transition[0] for transition in self.state_transitions}
        for view in views:
            if view['view_str'] in transition_views:
                self.logger.info("selected a transition view: %s" % view['view_str'])
                return view

        # no window transition found, just return a random view
        # view = views[0]
        # self.logger.info("selected a random view: %s" % view['view_str'])
        # return view

        # DroidBot stuck on current state, return None
        self.logger.info("no view could be selected in state: %s" % state.tag)
        return None

    def save_state_transition(self, event_str, old_state, new_state):
        """
        save the state transition
        @param event_str: str, representing the event cause the transition
        @param old_state: DeviceState
        @param new_state: DeviceState
        @return:
        """
        if event_str is None or old_state is None or new_state is None:
            return
        if new_state.is_different_from(old_state):
            self.state_transitions.add((event_str, old_state.tag, new_state.tag))

    def save_explored_view(self, state, view_str):
        """
        save the explored view
        @param state: DeviceState, where the view located
        @param view_str: str, representing a view
        @return:
        """
        if not state:
            return
        state_activity = state.foreground_activity
        self.explored_views.add((state_activity, view_str))

class RandomExplorationPolicy(UtgBasedInputPolicy):
    """
    Random exploration strategy
    """

    def __init__(self, device, app, random_input):
        super(RandomExplorationPolicy, self).__init__(device, app, random_input)
        self.logger = logging.getLogger(self.__class__.__name__)
        

        self.preferred_buttons = ["yes", "ok", "activate", "detail", "more", "access",
                                  "allow", "check", "agree", "try", "go", "next"]

        self.__nav_target = None
        self.__nav_num_steps = -1
        self.__num_restarts = 0
        self.__num_steps_outside = 0
        self.__event_trace = ""
        self.__missed_states = set()
        self.__random_explore = False

    def generate_event_based_on_utg(self):
        """
        generate an event based on current UTG
        @return: InputEvent
        """
        current_state = self.current_state
        self.logger.info("Current state: %s" % current_state.state_str)
        # if current_state.state_str in self.__missed_states:
        #     self.__missed_states.remove(current_state.state_str)
        if current_state.get_app_activity_depth(self.app) < 0:
            # If the app is not in the activity stack
            start_app_intent = self.app.get_start_intent()

            # It seems the app stucks at some state, has been
            # 1) force stopped (START, STOP)
            #    just start the app again by increasing self.__num_restarts
            # 2) started at least once and cannot be started (START)
            #    pass to let viewclient deal with this case
            # 3) nothing
            #    a normal start. clear self.__num_restarts.

            if self.__event_trace.endswith(EVENT_FLAG_START_APP + EVENT_FLAG_STOP_APP) \
                    or self.__event_trace.endswith(EVENT_FLAG_START_APP):
                self.__num_restarts += 1
                self.logger.info("The app had been restarted %d times.", self.__num_restarts)
            else:
                self.__num_restarts = 0

            # Check if we should try to start the app
            if not self.__event_trace.endswith(EVENT_FLAG_START_APP):
                if self.__num_restarts > MAX_NUM_RESTARTS:
                    # If the app had been restarted too many times, enter random mode
                    msg = "The app had been restarted too many times. Entering random mode."
                    self.logger.info(msg)
                    self.__random_explore = True
                else:
                    # Start the app
                    self.__event_trace += EVENT_FLAG_START_APP
                    self.logger.info("Trying to start the app...")
                    return IntentEvent(intent=start_app_intent)

        elif current_state.get_app_activity_depth(self.app) > 0:
            # If the app is in activity stack but is not in foreground
            self.__num_steps_outside += 1

            if self.__num_steps_outside > MAX_NUM_STEPS_OUTSIDE:
                # If the app has not been in foreground for too long, try to go back
                if self.__num_steps_outside > MAX_NUM_STEPS_OUTSIDE_KILL:
                    stop_app_intent = self.app.get_stop_intent()
                    go_back_event = IntentEvent(stop_app_intent)
                else:
                    go_back_event = KeyEvent(name="BACK")
                self.__event_trace += EVENT_FLAG_NAVIGATE
                self.logger.info("Going back to the app...")
                return go_back_event
        else:
            # If the app is in foreground
            self.__num_steps_outside = 0


        # Get all possible input events
        possible_events = current_state.get_possible_input_only_leaf_nodes(self.app.get_package_name())
        if len(possible_events) == 0:
            possible_events = current_state.get_possible_input()
        target_event = self._weighted_random_choice(possible_events)
        
        if target_event is None:
            self.logger.info("No possible events available. Trying to go back...")
            self.__event_trace += EVENT_FLAG_NAVIGATE
            return KeyEvent(name="BACK")
        
        if self.device is not None: # skip welcome may not have u2
            target_event.u2 = self.device.u2
        
        # Update event trace based on event type
        if hasattr(target_event, 'event_type'):
            if target_event.event_type in ['touch', 'long_touch', 'swipe', 'scroll', 'set_text', 'select']:
                self.__event_trace += EVENT_FLAG_TOUCH
            elif target_event.event_type == 'key':
                if target_event.name == 'BACK':
                    self.__event_trace += EVENT_FLAG_NAVIGATE
                else:
                    self.__event_trace += EVENT_FLAG_TOUCH
            elif target_event.event_type == 'intent':
                # Update event trace based on intent command type
                intent_cmd = getattr(target_event, 'intent', '')
                if 'start' in intent_cmd:
                    self.__event_trace += EVENT_FLAG_START_APP
                elif 'force-stop' in intent_cmd:
                    self.__event_trace += EVENT_FLAG_STOP_APP
                elif 'broadcast' in intent_cmd:
                    self.__event_trace += EVENT_FLAG_EXPLORE
                else:
                    # Default to explore for other intent types
                    self.__event_trace += EVENT_FLAG_EXPLORE
        
        return target_event

    def _weighted_random_choice(self, possible_events):
        """
        带权重的随机选择函数
        - touch: 最高权重 (50%)
        - scroll: 最低权重 (5%)
        - 其他: 中等权重 (15% 每个)
        """
        if not possible_events:
            return None
        
        # 定义事件类型的权重
        event_weights = {
            'touch': 50,          # 最高权重
            'long_touch': 15,     # 中等权重
            'swipe': 15,          # 中等权重
            'set_text': 20,       # 中等权重
            'select': 15,         # 中等权重
            'scroll': 20,          # 最低权重
            'key': 15,            # 中等权重
            'intent': 20,         # 较低权重
        }
        
        # 为每个事件分配权重
        weighted_events = []
        for event in possible_events:
            event_type = getattr(event, 'event_type', 'unknown')
            weight = event_weights.get(event_type, 10)  # 默认权重为10
            weighted_events.extend([event] * weight)
        
        # 如果所有事件都没有匹配到权重，回退到原始随机选择
        if not weighted_events:
            return random.choice(possible_events)
        
        return random.choice(weighted_events)


class UtgGreedySearchPolicy(UtgBasedInputPolicy):
    """
    DFS/BFS (according to search_method) strategy to explore UFG (new)
    """

    def __init__(self, device, app, random_input, search_method):
        super(UtgGreedySearchPolicy, self).__init__(device, app, random_input)
        self.logger = logging.getLogger(self.__class__.__name__)
        self.search_method = search_method

        self.preferred_buttons = ["yes", "ok", "activate", "detail", "more", "access",
                                  "allow", "check", "agree", "try", "go", "next"]

        self.__nav_target = None
        self.__nav_num_steps = -1
        self.__num_restarts = 0
        self.__num_steps_outside = 0
        self.__event_trace = ""
        self.__missed_states = set()
        self.__random_explore = False

    def generate_event_based_on_utg(self):
        """
        generate an event based on current UTG
        @return: InputEvent
        """
        current_state = self.current_state
        self.logger.info("Current state: %s" % current_state.state_str)
        if current_state.state_str in self.__missed_states:
            self.__missed_states.remove(current_state.state_str)

        if current_state.get_app_activity_depth(self.app) < 0:
            # If the app is not in the activity stack
            start_app_intent = self.app.get_start_intent()

            # It seems the app stucks at some state, has been
            # 1) force stopped (START, STOP)
            #    just start the app again by increasing self.__num_restarts
            # 2) started at least once and cannot be started (START)
            #    pass to let viewclient deal with this case
            # 3) nothing
            #    a normal start. clear self.__num_restarts.

            if self.__event_trace.endswith(EVENT_FLAG_START_APP + EVENT_FLAG_STOP_APP) \
                    or self.__event_trace.endswith(EVENT_FLAG_START_APP):
                self.__num_restarts += 1
                self.logger.info("The app had been restarted %d times.", self.__num_restarts)
            else:
                self.__num_restarts = 0

            # pass (START) through
            if not self.__event_trace.endswith(EVENT_FLAG_START_APP):
                if self.__num_restarts > MAX_NUM_RESTARTS:
                    # If the app had been restarted too many times, enter random mode
                    msg = "The app had been restarted too many times. Entering random mode."
                    self.logger.info(msg)
                    self.__random_explore = True
                else:
                    # Start the app
                    self.__event_trace += EVENT_FLAG_START_APP
                    self.logger.info("Trying to start the app...")
                    return IntentEvent(intent=start_app_intent)

        elif current_state.get_app_activity_depth(self.app) > 0:
            # If the app is in activity stack but is not in foreground
            self.__num_steps_outside += 1

            if self.__num_steps_outside > MAX_NUM_STEPS_OUTSIDE:
                # If the app has not been in foreground for too long, try to go back
                if self.__num_steps_outside > MAX_NUM_STEPS_OUTSIDE_KILL:
                    stop_app_intent = self.app.get_stop_intent()
                    go_back_event = IntentEvent(stop_app_intent)
                else:
                    go_back_event = KeyEvent(name="BACK")
                self.__event_trace += EVENT_FLAG_NAVIGATE
                self.logger.info("Going back to the app...")
                return go_back_event
        else:
            # If the app is in foreground
            self.__num_steps_outside = 0

        # Get all possible input events
        possible_events = current_state.get_possible_input()

        if self.random_input:
            random.shuffle(possible_events)

        if self.search_method == POLICY_GREEDY_DFS:
            possible_events.append(KeyEvent(name="BACK"))
        elif self.search_method == POLICY_GREEDY_BFS:
            possible_events.insert(0, KeyEvent(name="BACK"))

        # get humanoid result, use the result to sort possible events
        # including back events
        if self.device.humanoid is not None:
            possible_events = self.__sort_inputs_by_humanoid(possible_events)

        # If there is an unexplored event, try the event first
        for input_event in possible_events:
            if not self.utg.is_event_explored(event=input_event, state=current_state):
                self.logger.info("Trying an unexplored event.")
                self.__event_trace += EVENT_FLAG_EXPLORE
                return input_event

        target_state = self.__get_nav_target(current_state)
        if target_state:
            navigation_steps = self.utg.get_navigation_steps(from_state=current_state, to_state=target_state)
            if navigation_steps and len(navigation_steps) > 0:
                self.logger.info("Navigating to %s, %d steps left." % (target_state.state_str, len(navigation_steps)))
                self.__event_trace += EVENT_FLAG_NAVIGATE
                return navigation_steps[0][1]

        if self.__random_explore:
            self.logger.info("Trying random event.")
            random.shuffle(possible_events)
            return possible_events[0]

        # If couldn't find a exploration target, stop the app
        stop_app_intent = self.app.get_stop_intent()
        self.logger.info("Cannot find an exploration target. Trying to restart app...")
        self.__event_trace += EVENT_FLAG_STOP_APP
        return IntentEvent(intent=stop_app_intent)

    def __sort_inputs_by_humanoid(self, possible_events):
        if sys.version.startswith("3"):
            from xmlrpc.client import ServerProxy
        else:
            from xmlrpclib import ServerProxy
        proxy = ServerProxy("http://%s/" % self.device.humanoid)
        request_json = {
            "history_view_trees": self.humanoid_view_trees,
            "history_events": [x.__dict__ for x in self.humanoid_events],
            "possible_events": [x.__dict__ for x in possible_events],
            "screen_res": [self.device.display_info["width"],
                           self.device.display_info["height"]]
        }
        result = json.loads(proxy.predict(json.dumps(request_json)))
        new_idx = result["indices"]
        text = result["text"]
        new_events = []

        # get rid of infinite recursive by randomizing first event
        if not self.utg.is_state_reached(self.current_state):
            new_first = random.randint(0, len(new_idx) - 1)
            new_idx[0], new_idx[new_first] = new_idx[new_first], new_idx[0]

        for idx in new_idx:
            if isinstance(possible_events[idx], SetTextEvent):
                possible_events[idx].text = text
            new_events.append(possible_events[idx])
        return new_events

    def __get_nav_target(self, current_state):
        # If last event is a navigation event
        if self.__nav_target and self.__event_trace.endswith(EVENT_FLAG_NAVIGATE):
            navigation_steps = self.utg.get_navigation_steps(from_state=current_state, to_state=self.__nav_target)
            if navigation_steps and 0 < len(navigation_steps) <= self.__nav_num_steps:
                # If last navigation was successful, use current nav target
                self.__nav_num_steps = len(navigation_steps)
                return self.__nav_target
            else:
                # If last navigation was failed, add nav target to missing states
                self.__missed_states.add(self.__nav_target.state_str)

        reachable_states = self.utg.get_reachable_states(current_state)
        if self.random_input:
            random.shuffle(reachable_states)

        for state in reachable_states:
            # Only consider foreground states
            if state.get_app_activity_depth(self.app) != 0:
                continue
            # Do not consider missed states
            if state.state_str in self.__missed_states:
                continue
            # Do not consider explored states
            if self.utg.is_state_explored(state):
                continue
            self.__nav_target = state
            navigation_steps = self.utg.get_navigation_steps(from_state=current_state, to_state=self.__nav_target)
            if len(navigation_steps) > 0:
                self.__nav_num_steps = len(navigation_steps)
                return state

        self.__nav_target = None
        self.__nav_num_steps = -1
        return None

class UtgReplayPolicy(InputPolicy):
    """
    Replay DroidBot output generated by UTG policy
    """

    def __init__(self, device, app, replay_output):
        super(UtgReplayPolicy, self).__init__(device, app)
        self.logger = logging.getLogger(self.__class__.__name__)
        self.replay_output = replay_output

        event_dir = os.path.join(replay_output, "events")
        files = [os.path.join(event_dir, x) for x in
                 next(os.walk(event_dir))[2]
                 if x.endswith(".json")]
        def _event_index(path):
            base = os.path.basename(path)
            name, _ = os.path.splitext(base)
            try:
                return int(name.split('_')[-1])
            except Exception:
                return float('inf')
        # 自然排序：按 event_<num>.json 的 <num> 升序
        self.event_paths = sorted(files, key=_event_index)
        # skip HOME and start app intent
        self.device = device
        self.app = app
        self.event_idx = 1
        self.num_replay_tries = 0
        self.utg = UTG(device=device, app=app, random_input=None)
        self.last_event = None
        self.last_state = None
        self.current_state = None

    def generate_event(self):
        """
        generate an event based on replay_output
        @return: InputEvent
        """
        while self.event_idx < len(self.event_paths) and \
              self.num_replay_tries < MAX_REPLY_TRIES:
            self.num_replay_tries += 1
            current_state = self.device.get_current_state()
            if current_state is None:
                time.sleep(5)
                self.num_replay_tries = 0
                return KeyEvent(name="BACK")
            
            curr_event_idx = self.event_idx
            # self.__update_utg()
            self.current_state = current_state
            self.current_state.tag = str(curr_event_idx) # 按events数量命名，方便后续查看
            self.current_state.save2dir()
            if curr_event_idx < len(self.event_paths):
                event_path = self.event_paths[curr_event_idx]
                with open(event_path, "r") as f:
                    curr_event_idx += 1

                    self.logger.info("debug curr_event_idx: " + str(curr_event_idx))

                    if curr_event_idx!= 2:
                        try:
                            event_dict = json.load(f)
                        except Exception as e:
                            self.logger.info("Loading %s failed" % event_path + "curr_event_idx: " + str(curr_event_idx))
                            continue

                    # if event_dict["start_state"] != current_state.state_str:
                    #     continue
                    # if not self.device.is_foreground(self.app):
                    #     # if current app is in background, bring it to foreground
                    #     # component = self.app.get_package_name()
                    #     # if self.app.get_main_activity():
                    #     #     component += "/%s" % self.app.get_main_activity()
                    #     return IntentEvent(self.app.get_start_intent())
                    
                    self.logger.info("Replaying %s" % event_path + "curr_event_idx: " + str(curr_event_idx))
                    self.event_idx = curr_event_idx
                    self.num_replay_tries = 0
                    
                    # 跳过第2个事件，直接返回启动app的Intent
                    if curr_event_idx == 2: # 有些第二个event是空的
                        return IntentEvent(self.app.get_start_intent())
                    
                    event = InputEvent.from_dict(event_dict["event"])
                    event.u2 = self.device.u2
                    if isinstance(event, IntentEvent):
                        return event
                    elif isinstance(event, KeyEvent):
                        return event


                    check_result = self.check_which_exists(event)
                    print("debug check_result", check_result)
                    if check_result[0] is None:
                        self.logger.warning(f"Widget not found for event: {event_path}")
                        self.logger.info("Stopping replay due to widget not found")
                        self.current_state.tag = str(curr_event_idx) # 按events数量命名，方便后续查看
                        self.current_state.save2dir() # save the current state
                        self.input_manager.enabled = False
                        self.input_manager.stop()
                        break
                
                    
                    self.last_state = self.current_state
                    self.last_event = event
                    
                    
                    return event

            time.sleep(5)

        # raise InputInterruptedException("No more record can be replayed.")
    
    def check_if_same(self, current, record):
        if current is None or record is None:
            return False
        if current == record:
            return True
        return False

    def replace_view(self, event, current_view):
        event.view['resource_id'] = current_view['resource_id']
        event.view['text'] = current_view['text']
        event.view['content_description'] = current_view['content_description']
        event.view['class'] = current_view['class']
        event.view['instance'] = current_view['instance']
        event.view['bounds'] = current_view['bounds']
    
    def check_which_exists(self, event):
        resource_id = UtgReplayPolicy.__safe_dict_get(event.view, 'resource_id')
        text = UtgReplayPolicy.__safe_dict_get(event.view, 'text')
        content_description = UtgReplayPolicy.__safe_dict_get(event.view, 'content_description')
        class_name = UtgReplayPolicy.__safe_dict_get(event.view, 'class')
        instance = UtgReplayPolicy.__safe_dict_get(event.view, 'instance')

        u2 = self.device.u2
        

        if content_description is not None:
            if u2.exists(description=content_description, instance=instance):
                for current_view in self.current_state.views:
                    if self.check_if_same(current_view['content_description'], content_description) and self.check_if_same(current_view['instance'], instance):
                        self.replace_view(event, current_view)
                        break
                return 'content_description', content_description
        elif text is not None:
            if u2.exists(text=text, instance=instance):
                for current_view in self.current_state.views:
                    if self.check_if_same(current_view['text'], text) and self.check_if_same(current_view['instance'], instance):
                        self.replace_view(event, current_view)
                        break
                return 'text', text
        elif resource_id is not None:
            if u2.exists(resourceId=resource_id, instance=instance):
                for current_view in self.current_state.views:
                    if self.check_if_same(current_view['resource_id'], resource_id) and self.check_if_same(current_view['instance'], instance):
                        self.replace_view(event, current_view)
                        break
                return 'resource_id', resource_id
        elif class_name is not None:
            if u2.exists(className=class_name, instance=instance):
                for current_view in self.current_state.views:
                    if self.check_if_same(current_view['class'], class_name) and self.check_if_same(current_view['instance'], instance):
                        self.replace_view(event, current_view)
                        break
                return 'class_name', class_name
        elif class_name is not None and resource_id is not None and instance is not None:
            if u2.exists(className=class_name, resourceId=resource_id, instance=instance):
                for current_view in self.current_state.views:
                    if self.check_if_same(current_view['class'], class_name) and self.check_if_same(current_view['resource_id'], resource_id) and self.check_if_same(current_view['instance'], instance):
                        self.replace_view(event, current_view)
                        break
                return 'class_resource_instance', (class_name, resource_id, instance)
        
        return None, None
    

    @staticmethod
    def __safe_dict_get(view_dict, key, default=None):
        value = view_dict[key] if key in view_dict else None
        return value if value is not None else default

class GroundTruthPolicy(InputPolicy):
    """
    Replay DroidBot output generated by Ground Truth policy

    existing matched file: matched_element_<event_number>.json
    generating the following events
    """

    def __init__(self, device, app, replay_output, ground_truth_path):
        super(GroundTruthPolicy, self).__init__(device, app)
        self.logger = logging.getLogger(self.__class__.__name__)
        self.replay_output = replay_output

        
        event_dir = os.path.join(replay_output, "events")
        files = [os.path.join(event_dir, x) for x in
                 next(os.walk(event_dir))[2]
                 if x.endswith(".json")]
        def _event_index(path):
            base = os.path.basename(path)
            name, _ = os.path.splitext(base)
            try:
                return int(name.split('_')[-1])
            except Exception:
                return float('inf')
        # 自然排序：按 event_<num>.json 的 <num> 升序
        self.event_paths = sorted(files, key=_event_index)
        # skip HOME and start app intent
        self.device = device
        self.app = app
        self.event_idx = 1
        self.num_replay_tries = 0
        self.utg = UTG(device=device, app=app, random_input=None)
        self.last_event = None
        self.last_state = None
        self.current_state = None

        self.failed_event_number = 0
        self.matched_element = None
        self.load_ground_truth(ground_truth_path)


    def load_ground_truth(self, ground_truth_path):
        matched_files = glob.glob(os.path.join(ground_truth_path, "matched_element*.json"))
        if matched_files and len(matched_files) == 1:
            matched_file = matched_files[0]
            # 从文件名中提取数字（例如从matched_element_91.json中提取91）
            import re
            match = re.search(r'matched_element_(\d+)\.json', os.path.basename(matched_file))
            if match:
                self.failed_event_number = int(match.group(1))
            else:
                self.failed_event_number = 0
                
            with open(matched_file, "r") as f:
                self.matched_element = json.load(f)

            print("debug failed_event_number: ", self.failed_event_number)
            print("debug matched_element: ", self.matched_element)

    def generate_event(self):
        """
        generate an event based on replay_output
        @return: InputEvent
        """
        while self.event_idx < len(self.event_paths) and \
              self.num_replay_tries < MAX_REPLY_TRIES:
            self.num_replay_tries += 1
            current_state = self.device.get_current_state()
            if current_state is None:
                time.sleep(5)
                self.num_replay_tries = 0
                return KeyEvent(name="BACK")
            
            curr_event_idx = self.event_idx
            # self.__update_utg()
            self.current_state = current_state
            self.current_state.tag = str(curr_event_idx) # 按events数量命名，方便后续查看
            self.current_state.save2dir()
            if curr_event_idx < len(self.event_paths):
                event_path = self.event_paths[curr_event_idx]
                with open(event_path, "r") as f:
                    curr_event_idx += 1

                    self.logger.info("debug curr_event_idx: " + str(curr_event_idx))

                    if curr_event_idx!= 2:
                        try:
                            event_dict = json.load(f)
                        except Exception as e:
                            self.logger.info("Loading %s failed" % event_path + "curr_event_idx: " + str(curr_event_idx))
                            continue

                    # if event_dict["start_state"] != current_state.state_str:
                    #     continue
                    # if not self.device.is_foreground(self.app):
                    #     # if current app is in background, bring it to foreground
                    #     # component = self.app.get_package_name()
                    #     # if self.app.get_main_activity():
                    #     #     component += "/%s" % self.app.get_main_activity()
                    #     return IntentEvent(self.app.get_start_intent())
                    
                    self.logger.info("Replaying %s" % event_path + "curr_event_idx: " + str(curr_event_idx))
                    self.event_idx = curr_event_idx
                    self.num_replay_tries = 0
                    
                    # 跳过第2个事件，直接返回启动app的Intent
                    if curr_event_idx == 2: # 有些第二个event是空的
                        return IntentEvent(self.app.get_start_intent())
                    
                    event = InputEvent.from_dict(event_dict["event"])
                    event.u2 = self.device.u2
                    if isinstance(event, IntentEvent):
                        return event
                    elif isinstance(event, KeyEvent):
                        return event


                    check_result = self.check_which_exists(event)
                    print("debug check_result", check_result)
                    if check_result[0] is None:
                        self.logger.warning(f"Widget not found for event: {event_path}")
                        self.logger.info("Stopping replay due to widget not found")
                        self.current_state.tag = str(curr_event_idx) # 按events数量命名，方便后续查看
                        self.current_state.save2dir() # save the current state
                        self.input_manager.enabled = False
                        self.input_manager.stop()
                        break
                
                    
                    self.last_state = self.current_state
                    self.last_event = event
                    
                    
                    return event

            time.sleep(5)

        # raise InputInterruptedException("No more record can be replayed.")
    
    def check_if_same(self, current, record):
        if current is None or record is None:
            return False
        if current == record:
            return True
        return False

    def replace_view(self, event, current_view):
        event.view['resource_id'] = current_view['resource_id']
        event.view['text'] = current_view['text']
        event.view['content_description'] = current_view['content_description']
        event.view['class'] = current_view['class']
        event.view['instance'] = current_view['instance']
        event.view['bounds'] = current_view['bounds']
    
    
    def normalize(self, value):
        if value is None:
            return ""
        else:
            return value

    def compare_bounds(self, current_bounds, gt_bounds):
        str_cur_bounds = '['+str(current_bounds[0][0])+","+str(current_bounds[0][1])+"]["+str(current_bounds[1][0])+","+str(current_bounds[1][1])+']'
        return str_cur_bounds == str(gt_bounds)


    def check_which_exists(self, event):
        if self.failed_event_number == self.event_idx - 1:
            # using the matched element to replace the event
            for current_view in self.current_state.views:
                # normalize
                resource_id = self.normalize(current_view['resource_id'])
                text = self.normalize(current_view['text'])
                content_description = self.normalize(current_view['content_description'])
                class_name = self.normalize(current_view['class'])
                bounds = current_view['bounds']

                if self.check_if_same(resource_id, self.matched_element['resource-id']) and \
                   self.check_if_same(text, self.matched_element['text']) and \
                   self.check_if_same(content_description, self.matched_element['content-desc']) and \
                   self.check_if_same(class_name, self.matched_element['class']) and \
                   self.compare_bounds(bounds, self.matched_element['bounds']):
                    self.replace_view(event, current_view)
                    u2 = self.device.u2
                    return 'matched_element', self.matched_element
            
            return 'matched_element', None
        
        else:
        
            resource_id = GroundTruthPolicy.__safe_dict_get(event.view, 'resource_id')
            text = GroundTruthPolicy.__safe_dict_get(event.view, 'text')
            content_description = GroundTruthPolicy.__safe_dict_get(event.view, 'content_description')
            class_name = GroundTruthPolicy.__safe_dict_get(event.view, 'class')
            instance = GroundTruthPolicy.__safe_dict_get(event.view, 'instance')



            u2 = self.device.u2
            

            if content_description is not None:
                if u2.exists(description=content_description, instance=instance):
                    for current_view in self.current_state.views:
                        if self.check_if_same(current_view['content_description'], content_description) and self.check_if_same(current_view['instance'], instance):
                            self.replace_view(event, current_view)
                            break
                    return 'content_description', content_description
            elif text is not None:
                if u2.exists(text=text, instance=instance):
                    for current_view in self.current_state.views:
                        if self.check_if_same(current_view['text'], text) and self.check_if_same(current_view['instance'], instance):
                            self.replace_view(event, current_view)
                            break
                    return 'text', text
            elif resource_id is not None:
                if u2.exists(resourceId=resource_id, instance=instance):
                    for current_view in self.current_state.views:
                        if self.check_if_same(current_view['resource_id'], resource_id) and self.check_if_same(current_view['instance'], instance):
                            self.replace_view(event, current_view)
                            break
                    return 'resource_id', resource_id
            elif class_name is not None:
                if u2.exists(className=class_name, instance=instance):
                    for current_view in self.current_state.views:
                        if self.check_if_same(current_view['class'], class_name) and self.check_if_same(current_view['instance'], instance):
                            self.replace_view(event, current_view)
                            break
                    return 'class_name', class_name
            elif class_name is not None and resource_id is not None and instance is not None:
                if u2.exists(className=class_name, resourceId=resource_id, instance=instance):
                    for current_view in self.current_state.views:
                        if self.check_if_same(current_view['class'], class_name) and self.check_if_same(current_view['resource_id'], resource_id) and self.check_if_same(current_view['instance'], instance):
                            self.replace_view(event, current_view)
                            break
                    return 'class_resource_instance', (class_name, resource_id, instance)
            
            return None, None
    

    @staticmethod
    def __safe_dict_get(view_dict, key, default=None):
        value = view_dict[key] if key in view_dict else None
        return value if value is not None else default


class MatchingPolicy(InputPolicy):
    """
    Replay DroidBot output generated by Matching policy

    find the target element
    """

    def __init__(self, device, app, replay_output, failed_replay_output, output_dir):
        super(MatchingPolicy, self).__init__(device, app)
        self.logger = logging.getLogger(self.__class__.__name__)
        self.replay_output = replay_output # 正常record的output
        self.failed_replay_output = failed_replay_output # 失败replay的output
        self.output_dir = output_dir # 输出dir

        event_dir = os.path.join(replay_output, "events")
        files = [os.path.join(event_dir, x) for x in
                 next(os.walk(event_dir))[2]
                 if x.endswith(".json")]
        def _event_index(path):
            base = os.path.basename(path)
            name, _ = os.path.splitext(base)
            try:
                return int(name.split('_')[-1])
            except Exception:
                return float('inf')
        # 自然排序：按 event_<num>.json 的 <num> 升序
        self.event_paths = sorted(files, key=_event_index)
        # skip HOME and start app intent
        self.device = device
        self.app = app
        self.event_idx = 1
        self.num_replay_tries = 0
        self.utg = UTG(device=device, app=app, random_input=None)
        self.last_event = None
        self.last_state = None
        self.current_state = None

        # 失败事件相关
        self.failed_event_number = 0
        self.failed_event_path = None
        self.failed_event_json = None
        self.failed_event_xml_tree = None
        self.failed_event_png_path = None
        self.failed_event_png = None
        self.failed_event_png_next = None
        self.failed_event_png_next_path = None
        self.load_failed_event() # 加载failed_event_number，failed_event_json，failed_event_xml_tree，failed_event_png

        # 模式管理，前面是回放模式，后面是修复模式
        self.mode = "replay"  # 两种模式: "replay"（回放模式）和 "repair"（修复模式）

        # 修复过程追踪
        self.repair_trace = []  # 修复过程的完整轨迹，每一步包含：{step_number, matched_element, screenshot}
        self.try_count = 0  # 尝试查找目标元素的次数
        self.exploration_step = 0  # 探索步数计数器，全局统一管理
        # 探索状态管理（用于随机探索fallback）
        self.visited_states = set()  # 已访问的状态hash，避免重复探索

        # 反馈机制：记录错误的匹配结果，重试时排除
        self.excluded_views = []  # 被排除的 view（之前匹配成功但后续失败的）
        self.last_repaired_view = None  # 上一次修复匹配到的 view
        self.exploration_retry_count = 0  # 探索重试次数
        self.max_exploration_retries = 3  # 最大重试次数

        # Activity 路径追踪（用于判断 back 可行性）
        self.activity_trace = []  # 记录每个 event 执行后的 activity 变化
        self.exploration_activity_trace = []  # 记录探索过程中的 activity 变化

        # 临时文件保存目录
        self.exploration_tmp_dir = os.path.join(self.output_dir, "exploration_tmp/")
        os.makedirs(self.exploration_tmp_dir, exist_ok=True)

        # 防止dfs死循环 记录已访问的导航元素
        self.visited_navigation_elements = set()  # 记录已选择过的导航元素 (activity, resource_id, class, content_desc, click_type)

        # 配置 logger 输出到文件
        self._setup_file_logger()

        # LLM配置
        self.llm_api_key = os.getenv("API_KEY")  # OpenAI API Key

    def _setup_file_logger(self):
        """配置 logger 输出到 exploration_tmp 目录下的文件"""
        log_file = os.path.join(self.exploration_tmp_dir, "repair.log")

        # 创建文件 handler
        file_handler = logging.FileHandler(log_file, mode='w', encoding='utf-8')
        file_handler.setLevel(logging.DEBUG)

        # 设置格式
        formatter = logging.Formatter(
            '[%(asctime)s] %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        file_handler.setFormatter(formatter)

        # 添加到 logger
        self.logger.addHandler(file_handler)
        self.logger.setLevel(logging.DEBUG)

        self.logger.info(f"Logger initialized, log file: {log_file}")

    def load_failed_event(self):

        # 1. 加载failed_event_number
        all_event_files = glob.glob(os.path.join(self.failed_replay_output, "events/*.json"))
        event_numbers = [int(os.path.basename(file).split('_')[-1].split('.')[0]) for file in all_event_files]
        self.failed_event_number = max(event_numbers) + 1

        # 2. 加载failed_event_json
        failed_event_json_path = os.path.join(self.replay_output, f"events/event_{self.failed_event_number}.json")
        self.failed_event_path = failed_event_json_path
        with open(failed_event_json_path, 'r') as f:
            self.failed_event_json = json.load(f)

        # 3. 加载failed_event_xml_tree
        failed_event_xml_tree_path = os.path.join(self.replay_output, f"xmls/xml_{self.failed_event_number-1}.xml")
        with open(failed_event_xml_tree_path, 'r') as f:
            self.failed_event_xml_tree = ET.parse(f)

        # 4. 加载failed_event_png
        failed_event_png_path = os.path.join(self.replay_output, f"states/screen_{self.failed_event_number-1}.png")
        self.failed_event_png_path = failed_event_png_path
        self.failed_event_png = read_image(failed_event_png_path) # PIL.Image.Image

        # 5. 加载failed_event_png_next
        failed_event_png_next_path = os.path.join(self.replay_output, f"states/screen_{self.failed_event_number}.png")
        self.failed_event_png_next_path = failed_event_png_next_path
        self.failed_event_png_next = read_image(failed_event_png_next_path) # PIL.Image.Image
    
   
    def normalize(self, value):
        if value is None:
            return ""
        else:
            return value

    def compare_bounds(self, current_bounds, gt_bounds):
        str_cur_bounds = '['+str(current_bounds[0][0])+","+str(current_bounds[0][1])+"]["+str(current_bounds[1][0])+","+str(current_bounds[1][1])+']'
        return str_cur_bounds == str(gt_bounds)


    def generate_event(self):
        """
        generate an event based on replay_output
        @return: InputEvent
        """
        while self.event_idx < len(self.event_paths) and \
              self.num_replay_tries < MAX_REPLY_TRIES:
            self.num_replay_tries += 1
            current_state = self.device.get_current_state()
            if current_state is None:
                time.sleep(5)
                self.num_replay_tries = 0
                return KeyEvent(name="BACK")

            curr_event_idx = self.event_idx
            # self.__update_utg()
            self.current_state = current_state
            self.current_state.tag = str(curr_event_idx) # 按events数量命名，方便后续查看
            self.current_state.save2dir()

            # 更新上一个 event 的 activity_after（replay 阶段）
            if len(self.activity_trace) > 0 and self.activity_trace[-1]['activity_after'] is None:
                self.activity_trace[-1]['activity_after'] = current_state.foreground_activity

            if curr_event_idx < len(self.event_paths):
                event_path = self.event_paths[curr_event_idx]
                with open(event_path, "r") as f:
                    curr_event_idx += 1

                    time.sleep(2) # 等待1秒，让app加载完成

                    self.logger.info("debug curr_event_idx: " + str(curr_event_idx))

                    if curr_event_idx!= 2:
                        try:
                            event_dict = json.load(f)
                        except Exception as e:
                            self.logger.info("Loading %s failed" % event_path + "curr_event_idx: " + str(curr_event_idx))
                            continue

                    self.logger.info("Replaying %s" % event_path + "curr_event_idx: " + str(curr_event_idx))
                    self.event_idx = curr_event_idx
                    self.num_replay_tries = 0
                    
                    # 跳过第2个事件，直接返回启动app的Intent
                    if curr_event_idx == 2: # 有些第二个event是空的
                        return IntentEvent(self.app.get_start_intent())

                    if self.app.get_package_name() == "com.appmindlab.nano" and curr_event_idx == 3:
                        # 这个app有问题，重启之后再重启一次
                        self.device.adb.shell("am force-stop %s" % self.app.get_package_name())
                        self.device.start_app(self.app)
                        time.sleep(2)

                    
                    
                    event = InputEvent.from_dict(event_dict["event"])
                    event.u2 = self.device.u2
                    if isinstance(event, IntentEvent):
                        return event
                    elif isinstance(event, KeyEvent):
                        return event

                    # 如果到达失败事件，切换到探索模式
                    if curr_event_idx == self.failed_event_number:
                        self.logger.info("Reached failed event, switching to exploration mode")
                        self.mode = "explore"
                        self.target_event = event
                        time.sleep(1)
                        return self.start_exploration()
                    check_result = self.check_which_exists(event)
                    print("debug check_result", check_result)
                    if check_result[0] is None:
                        self.logger.warning(f"Widget not found for event: {event_path}")

                        # 检查是否是修复后的 event 失败了（说明之前的匹配是错的，需要重试）
                        if curr_event_idx == self.failed_event_number + 1:
                            self.logger.info("Repaired event failed! Adding to excluded list and retrying...")
                            # 将错误的 view 加入排除列表
                            if self.last_repaired_view:
                                self.excluded_views.append(self.last_repaired_view)
                            self.last_repaired_view = None
                            self.exploration_retry_count += 1
                            self.logger.info(f"Retry {self.exploration_retry_count}/{self.max_exploration_retries}, excluded {len(self.excluded_views)} views")

                            # 检查是否还有重试机会
                            # if self.exploration_retry_count < self.max_exploration_retries:
                            #     # 重启 app 并重放到 failed_event 之前
                            #     self.logger.info("Restarting app and replaying to retry exploration...")

                            #     # 重置 event_idx 到 failed_event
                            #     self.event_idx = self.failed_event_number

                            #     # 清空 activity trace，重新开始
                            #     self.activity_trace = []
                            #     self.exploration_activity_trace = []

                            #     # 重新开始探索（会先重放到 failed_event）
                            #     return self._restart_and_replay_to_failed_event()
                            # else:
                            #     self.logger.warning(f"Max retries ({self.max_exploration_retries}) reached, giving up")

                        self.logger.info("Stopping replay due to widget not found")
                        self.current_state.tag = str(curr_event_idx) # 按events数量命名，方便后续查看
                        self.current_state.save2dir() # save the current state
                        self.input_manager.enabled = False
                        self.input_manager.stop()
                        break

                    if curr_event_idx == self.failed_event_number + 2:
                        # 说明修好了，直接停止，不需要再replay了
                        self.logger.info("Repaired event succeeded! Stopping replay...")
                        self.input_manager.enabled = False
                        self.input_manager.stop()
                        break



                    self.last_state = self.current_state
                    self.last_event = event

                    # 记录 activity 变化（用于后续 back 判断）
                    activity_before = self.current_state.foreground_activity
                    self.activity_trace.append({
                        'event_idx': curr_event_idx,
                        'activity_before': activity_before,
                        'activity_after': None  # 执行后更新
                    })

                    return event

            time.sleep(5)

    def start_exploration(self, max_steps=15):
        """
        探索模式：每一步先查找目标元素，找不到再让 LLM 推荐导航

        Args:
            max_steps: 最大探索步数

        流程：
        每一步：
        1. 获取当前页面可点击元素
        2. 查找目标元素
        3. 找到 → 验证（cross page 需要 LLM judge）→ 成功返回
        4. 没找到 → LLM 推荐导航元素 → 点击 → 进入下一步
        """

        # 记录探索开始时的 activity，用于后续返回导航和重试
        start_activity = self.current_state.foreground_activity
        self.start_activity_before_repair = start_activity  # 保存为实例变量，重试时用
        self.logger.info(f"Exploration starting from activity: {start_activity}")

        # 清空探索阶段的 activity trace
        self.exploration_activity_trace = []

        # 重置探索步数计数器
        self.exploration_step = 0

        while self.exploration_step < max_steps:
            cross_page = (self.exploration_step > 0)  # step 0 是 same page，step 1+ 是 cross page
            self.logger.info(f"=== Exploration step {self.exploration_step}/{max_steps} ({'cross page' if cross_page else 'same page'}) ===")

            # 1. 获取当前页面所有可点击的元素
            possible_events = self.current_state.get_possible_input(package_name=self.app.get_package_name())
            time.sleep(1)
            if len(possible_events) == 0:
                self.logger.warning("No clickable elements found, pressing BACK to return...")
                self.device.send_event(KeyEvent(name="BACK"))
                time.sleep(0.5)
                self.current_state = self.device.get_current_state()
                self.exploration_step += 1
                continue

            #补充scrollable事件
            scrollable_events = []
            for event in possible_events:
                if event.event_type == "scroll":
                    scrollable_events.append(event)

            # 过滤 按照 UIMatch 的规则过滤
            self.logger.info(f"Filtering events: original count = {len(possible_events)}")
            possible_events = self._filter_events_by_rules(possible_events)
            if self.app.get_package_name() == "com.amaze.filemanager" or self.app.get_package_name() == "com.appmindlab.nano":
                possible_events = self.current_state.get_possible_input_only_leaf_nodes(self.app.get_package_name())
            self.logger.info(f"After filtering: {len(possible_events)} events")


            # 2. 在当前页面查找目标元素
            self.logger.info(f"Step {self.exploration_step}: Searching for target element...")
            matched_view, matching_method = self.find_target_element_in_page(self.current_state, self.exploration_step, cross_page)
            self.logger.info(f"Element match result: {matched_view is not None}, method: {matching_method}")

            # 3. Same page 处理（包含 scroll voting 机制）
            if not cross_page:
                current_activity = self.current_state.foreground_activity

                # 过滤出可用的scroll events
                scroll_events = self.filter_scroll_events(scrollable_events)

                # 如果有 scroll events，使用 voting 机制（遍历所有 scrollable views）
                if len(scroll_events) > 0 and current_activity == start_activity:
                    self.logger.info(f"Same page with {len(scroll_events)} scrollable views, using voting mechanism...")

                    # 记录执行的scroll，用于后续逆向恢复
                    executed_scrolls = []  # [(scroll_event, direction), ...]

                    # 收集多次查找的结果进行 voting
                    candidates = {}  # {view_str: {'view': view, 'count': count, 'last_state': state}}

                    # 第一次查找（scroll 前的当前页面）
                    if matched_view:
                        view_str = matched_view.get('view_str', '')
                        candidates[view_str] = {
                            'view': matched_view,
                            'count': 1,
                            'last_state': self.current_state,
                            'matching_method': matching_method,
                            'scroll_index': 0  # scroll前找到的，索引为0
                        }
                        self.logger.info(f"Initial match found (before scroll): {view_str[:20]}...")

                    # 遍历所有 scrollable views 进行 scroll
                    for i, scroll_event in enumerate(scroll_events):
                        state_before = self.current_state.state_str
                        # 记录scroll前的截图路径（用于相似度比较）
                        screenshot_before = self.current_state.screenshot_path

                        self.logger.info(f"Scroll {i + 1}/{len(scroll_events)} for voting...")
                        self.device.send_event(scroll_event, probe=True) #滑动距离较小
                        executed_scrolls.append(scroll_event)  # 记录执行的scroll
                        time.sleep(0.5)
                        self.exploration_step += 1

                        new_state = self.device.get_current_state()
                        self.current_state = new_state

                        # 检查scroll前后截图相似度，如果 > 0.95 说明scroll无效，跳过
                        screenshot_after = new_state.screenshot_path if new_state else None
                        if screenshot_before and screenshot_after and os.path.exists(screenshot_before) and os.path.exists(screenshot_after):
                            try:
                                img_before = read_image(screenshot_before)
                                img_after = read_image(screenshot_after)
                                similarity = compute_ssim(img_before, img_after)
                                if similarity > 0.95:
                                    self.logger.info(f"Scroll had no effect (similarity={similarity:.4f} > 0.95), skipping...")
                                    continue
                            except Exception as e:
                                self.logger.warning(f"Failed to compare screenshots: {e}")

                        # 在新页面查找目标（这会保存 screen_same_page_{step}.png 和 xml_same_page_{step}.xml）
                        new_matched, new_matching_method = self.find_target_element_in_page(self.current_state, self.exploration_step, cross_page)

                        # 记录 scroll 到 trace（使用 find_target_element_in_page 保存的截图路径）

                        scroll_trace = {
                            'step': self.exploration_step,
                            'action': 'scroll',
                            'direction': scroll_event.direction,
                            'event': {
                                'type': 'scroll',
                                'view': scroll_event.view if hasattr(scroll_event, 'view') else None
                            },
                            'state_before': state_before,
                            'state_after': new_state.state_str if new_state else None,
                            'screenshot': os.path.join(self.exploration_tmp_dir, f"states/screen_same_page_{self.exploration_step}.png"),
                            'xml': os.path.join(self.exploration_tmp_dir, f"xmls/xml_same_page_{self.exploration_step}.xml"),
                            'found_target': new_matched is not None,
                            'matching_method': new_matching_method
                        }
                        self.repair_trace.append(scroll_trace)

                        if new_matched:
                            view_str = new_matched.get('view_str', '')
                            current_scroll_index = i + 1  # 第i次scroll后，索引为i+1
                            if view_str in candidates:
                                candidates[view_str]['count'] += 1
                                candidates[view_str]['view'] = new_matched  # 更新为最新的 view
                                candidates[view_str]['last_state'] = self.current_state
                                candidates[view_str]['matching_method'] = new_matching_method
                                # 保持最早出现的scroll_index，不更新
                                self.logger.info(f"View {view_str[:20]}... found again, count={candidates[view_str]['count']}, first_scroll_index={candidates[view_str]['scroll_index']}")
                            else:
                                candidates[view_str] = {
                                    'view': new_matched,
                                    'count': 1,
                                    'last_state': self.current_state,
                                    'matching_method': new_matching_method,
                                    'scroll_index': current_scroll_index  # 记录第一次出现时的scroll索引
                                }
                                self.logger.info(f"New candidate found: {view_str[:20]}..., scroll_index={current_scroll_index}")

                    # Voting：选择最佳候选
                    # 如果仅有一个非 LLM 匹配，直接确定为最佳；否则按 count 投票
                    should_return = False
                    repaired_event = None

                    if candidates:
                        # 输出所有 scroll candidates 到 json 文件
                        scroll_candidates_output = []
                        for view_str, candidate_info in candidates.items():
                            scroll_candidates_output.append({
                                'view_str': view_str,
                                'count': candidate_info['count'],
                                'scroll_index': candidate_info.get('scroll_index', -1),
                                'matching_method': candidate_info['matching_method'],
                                'view': candidate_info['view']
                            })
                        scroll_candidates_path = os.path.join(self.exploration_tmp_dir, "repair_logs", f"scroll_candidates_event_{self.failed_event_number}.json")
                        # 确保目录存在
                        repair_logs_dir = os.path.join(self.exploration_tmp_dir, "repair_logs")
                        if not os.path.exists(repair_logs_dir):
                            os.makedirs(repair_logs_dir)
                        with open(scroll_candidates_path, 'w') as f:
                            json.dump({
                                'failed_event_number': self.failed_event_number,
                                'total_candidates': len(candidates),
                                'candidates': scroll_candidates_output
                            }, f, indent=2, ensure_ascii=False)
                        self.logger.info(f"Saved scroll candidates to: {scroll_candidates_path}")

                        # 找非 LLM 匹配的候选（这些匹配准确率高，但仍需 LLM judge 验证）
                        non_llm_candidates = {k: v for k, v in candidates.items()
                                              if v['matching_method'] and v['matching_method'] != 'llm'}

                        selection_method = None  # 用于记录选择方式
                        best_candidate = None
                        matched_view = None

                        if len(non_llm_candidates) == 1:
                            # 仅有一个非 LLM 匹配，选为最佳候选
                            best_view_str = list(non_llm_candidates.keys())[0]
                            best_candidate = non_llm_candidates[best_view_str]
                            matched_view = best_candidate['view']
                            self.current_state = best_candidate['last_state']
                            selection_method = 'direct_non_llm'
                            self.logger.info(f"Direct match: exactly one non-LLM candidate (method={best_candidate['matching_method']})")
                        elif len(candidates) == 1:
                            # 只有一个候选，选为最佳候选
                            best_view_str = list(candidates.keys())[0]
                            best_candidate = candidates[best_view_str]
                            matched_view = best_candidate['view']
                            self.current_state = best_candidate['last_state']
                            selection_method = 'single_candidate'
                            self.logger.info(f"Single candidate: only one candidate available (method={best_candidate['matching_method']})")
                        else:
                            # 有多个候选 → 使用 LLM 选择
                            self.logger.info(f"Using LLM to select best candidate from {len(candidates)} candidates (non-LLM count={len(non_llm_candidates)})...")
                            result = self.llm_select_best_candidate(candidates)

                            if result:
                                best_view_str, best_candidate = result
                                matched_view = best_candidate['view']
                                self.current_state = best_candidate['last_state']
                                selection_method = 'llm_select'
                                self.logger.info(f"LLM selected candidate: {best_view_str[:30]}..., method={best_candidate['matching_method']}")
                            else:
                                self.logger.info("LLM selected NONE - no matching candidate")

                        # 选出候选后，统一调用 llm_judge_exploration_success 进行最终验证
                        if best_candidate:
                            self.logger.info(f"Calling llm_judge_exploration_success to verify the selected candidate...")
                            # 这里不传入matched view，只想让judge是否在当前页面，也就是页面是否正确
                            judge_result = self.llm_judge_exploration_success(matched_view=matched_view)
                            self.logger.info(f"LLM judge result: {judge_result}")
                        else:
                            judge_result = False

                        if judge_result:
                            self.logger.info("✓ Found target element (same page with scroll voting)")
                            self.exploration_step += 1  # Increment step for match_found record

                            self.repair_trace.append({
                                'step': self.exploration_step,
                                'action': 'match_found',
                                'event': None,
                                'state_after': self.current_state.state_str,
                                'screenshot': os.path.join(self.exploration_tmp_dir, f"states/screen_same_page_{self.exploration_step}.png"),
                                'xml': os.path.join(self.exploration_tmp_dir, f"xmls/xml_same_page_{self.exploration_step}.xml"),
                                'found_target': True,
                                'matched_view': matched_view,
                                'judge_result': judge_result,
                                'selection_method': selection_method,
                                'voting_count': best_candidate['count'],
                                'total_candidates': len(candidates),
                                'matching_method': best_candidate['matching_method']
                            })

                            repaired_event = self._create_repaired_event(matched_view)
                            self.last_repaired_view = matched_view

                            repaired_event_info = {
                                'tag': f"repaired_event_step_{self.exploration_step}",
                                'event': {
                                    'event_type': repaired_event.event_type if hasattr(repaired_event, 'event_type') else 'touch',
                                    'log_lines': None,
                                    'x': None,
                                    'y': None,
                                    'view': matched_view
                                },
                                'start_state': self.current_state.state_str if self.current_state else None,
                                'stop_state': None,
                                'event_str': repaired_event.get_event_str(self.current_state) if hasattr(repaired_event, 'get_event_str') else str(repaired_event)
                            }
                            event_dir = os.path.join(self.exploration_tmp_dir, "events")
                            if not os.path.exists(event_dir):
                                os.makedirs(event_dir)
                            repaired_event_path = os.path.join(event_dir, f"event_repaired_step_{self.exploration_step}.json")
                            with open(repaired_event_path, 'w') as f:
                                json.dump(repaired_event_info, f, indent=2, ensure_ascii=False)
                            self.logger.info(f"Saved repaired event to: {repaired_event_path}")
                            should_return = True
                        else:
                            self.logger.info("Voting best candidate failed LLM judge, continuing to navigation...")
                            matched_view = None  # 清空，继续到导航逻辑
                    else:
                        self.logger.info("No candidates found after scroll voting")
                        matched_view = None

                    # 成功找到目标，需要判断是否要逆向scroll回到目标元素可见的位置
                    if should_return:
                        target_scroll_index = best_candidate.get('scroll_index', 0)
                        current_scroll_count = len(executed_scrolls)
                        reverse_count = current_scroll_count - target_scroll_index

                        if reverse_count > 0:
                            self.logger.info(f"Target found at scroll_index={target_scroll_index}, current at {current_scroll_count}, reversing {reverse_count} scrolls...")
                            reverse_dir = {'down': 'up', 'up': 'down', 'right': 'left', 'left': 'right'}
                            # 从最后执行的scroll开始逆向
                            for j in range(reverse_count):
                                scroll_event = executed_scrolls[current_scroll_count - 1 - j]
                                state_before = self.current_state.state_str if self.current_state else None
                                scroll_event.direction = reverse_dir[scroll_event.direction]
                                self.device.send_event(scroll_event)
                                time.sleep(0.3)
                                self.exploration_step += 1
                                self.current_state = self.device.get_current_state()

                                # 保存逆向scroll后的截图，方便追踪
                                if self.current_state:
                                    self.current_state.tag = f"same_page_{self.exploration_step}"
                                    state_dir = os.path.join(self.exploration_tmp_dir, "states")
                                    self.current_state.save2dir(state_dir)

                                # 记录逆向scroll到trace
                                self.repair_trace.append({
                                    'step': self.exploration_step,
                                    'action': 'reverse_scroll',
                                    'direction': scroll_event.direction,
                                    'event': {
                                        'type': 'scroll',
                                        'view': scroll_event.view if hasattr(scroll_event, 'view') else None
                                    },
                                    'state_before': state_before,
                                    'state_after': self.current_state.state_str if self.current_state else None,
                                    'screenshot': os.path.join(self.exploration_tmp_dir, f"states/screen_same_page_{self.exploration_step}.png"),
                                    'xml': os.path.join(self.exploration_tmp_dir, f"xmls/xml_same_page_{self.exploration_step}.xml")
                                })

                        self.save_repair_trace()
                        return repaired_event

                    # 失败时逆向scroll恢复页面状态，为后续cross page逻辑做准备
                    if executed_scrolls:
                        self.logger.info(f"Reversing {len(executed_scrolls)} scroll operations to restore page state...")
                        reverse_dir = {'down': 'up', 'up': 'down', 'right': 'left', 'left': 'right'}
                        for scroll_event in reversed(executed_scrolls):
                            state_before = self.current_state.state_str if self.current_state else None
                            scroll_event.direction = reverse_dir[scroll_event.direction]
                            self.device.send_event(scroll_event)
                            time.sleep(0.3)
                            self.exploration_step += 1
                            self.current_state = self.device.get_current_state()

                            # 保存逆向scroll后的截图，方便追踪
                            if self.current_state:
                                self.current_state.tag = f"same_page_{self.exploration_step}"
                                state_dir = os.path.join(self.exploration_tmp_dir, "states")
                                self.current_state.save2dir(state_dir)

                            # 记录逆向scroll到trace
                            self.repair_trace.append({
                                'step': self.exploration_step,
                                'action': 'reverse_scroll',
                                'direction': scroll_event.direction,
                                'event': {
                                    'type': 'scroll',
                                    'view': scroll_event.view if hasattr(scroll_event, 'view') else None
                                },
                                'state_before': state_before,
                                'state_after': self.current_state.state_str if self.current_state else None,
                                'screenshot': os.path.join(self.exploration_tmp_dir, f"states/screen_same_page_{self.exploration_step}.png"),
                                'xml': os.path.join(self.exploration_tmp_dir, f"xmls/xml_same_page_{self.exploration_step}.xml")
                            })

                else:
                    # Same page 没有 scroll events，直接判断一次
                    if matched_view:
                        self.logger.info(f"Step {self.exploration_step}: Found target (same page, no scroll), using LLM to judge...")
                        # 这里不传入matched view，只想让judge是否在当前页面，也就是页面是否正确
                        judge_result = self.llm_judge_exploration_success(matched_view=matched_view)
                        self.logger.info(f"LLM judge result: {judge_result}")

                        if judge_result:
                            self.logger.info("✓ Found target element (same page, no scroll)")

                            self.repair_trace.append({
                                'step': self.exploration_step,
                                'action': 'match_found',
                                'event': None,
                                'state_after': self.current_state.state_str,
                                'screenshot': os.path.join(self.exploration_tmp_dir, f"states/screen_same_page_{self.exploration_step}.png"),
                                'xml': os.path.join(self.exploration_tmp_dir, f"xmls/xml_same_page_{self.exploration_step}.xml"),
                                'found_target': True,
                                'matched_view': matched_view,
                                'judge_result': judge_result,
                                'matching_method': matching_method
                            })

                            repaired_event = self._create_repaired_event(matched_view)
                            self.last_repaired_view = matched_view

                            repaired_event_info = {
                                'tag': f"repaired_event_step_{self.exploration_step}",
                                'event': {
                                    'event_type': repaired_event.event_type if hasattr(repaired_event, 'event_type') else 'touch',
                                    'log_lines': None,
                                    'x': None,
                                    'y': None,
                                    'view': matched_view
                                },
                                'start_state': self.current_state.state_str if self.current_state else None,
                                'stop_state': None,
                                'event_str': repaired_event.get_event_str(self.current_state) if hasattr(repaired_event, 'get_event_str') else str(repaired_event)
                            }
                            event_dir = os.path.join(self.exploration_tmp_dir, "events")
                            if not os.path.exists(event_dir):
                                os.makedirs(event_dir)
                            repaired_event_path = os.path.join(event_dir, f"event_repaired_step_{self.exploration_step}.json")
                            with open(repaired_event_path, 'w') as f:
                                json.dump(repaired_event_info, f, indent=2, ensure_ascii=False)
                            self.logger.info(f"Saved repaired event to: {repaired_event_path}")

                            self.save_repair_trace()
                            return repaired_event
                        else:
                            self.logger.info("Same page judge failed, continuing to navigation...")
                            matched_view = None

            # 4. Cross page 处理
            if cross_page and matched_view:
                self.logger.info(f"Step {self.exploration_step}: Found potential target (cross page), using LLM to judge...")
                # 这里不传入matched view，只想让judge是否在当前页面，也就是页面是否正确
                judge_result = self.llm_judge_exploration_success(matched_view=matched_view)
                self.logger.info(f"LLM judge result: {judge_result}")

                if judge_result:
                    self.logger.info("✓ Found target element (cross page, judge succeeded)")

                    step_info = {
                        'step': self.exploration_step,
                        'action': 'match_found',
                        'event': None,
                        'state_after': self.current_state.state_str,
                        'screenshot': os.path.join(self.exploration_tmp_dir, f"states/screen_same_page_{self.exploration_step}.png"),
                        'xml': os.path.join(self.exploration_tmp_dir, f"xmls/xml_same_page_{self.exploration_step}.xml"),
                        'found_target': True,
                        'matched_view': matched_view,
                        'judge_result': judge_result,
                        'matching_method': matching_method
                    }
                    self.repair_trace.append(step_info)

                    repaired_event = self._create_repaired_event(matched_view)
                    self.last_repaired_view = matched_view

                    repaired_event_info = {
                        'tag': f"repaired_event_step_{self.exploration_step}",
                        'event': {
                            'event_type': repaired_event.event_type if hasattr(repaired_event, 'event_type') else 'touch',
                            'log_lines': None,
                            'x': None,
                            'y': None,
                            'view': matched_view
                        },
                        'start_state': self.current_state.state_str if self.current_state else None,
                        'stop_state': None,
                        'event_str': repaired_event.get_event_str(self.current_state) if hasattr(repaired_event, 'get_event_str') else str(repaired_event)
                    }
                    event_dir = os.path.join(self.exploration_tmp_dir, "events")
                    if not os.path.exists(event_dir):
                        os.makedirs(event_dir)
                    repaired_event_path = os.path.join(event_dir, f"event_repaired_step_{self.exploration_step}.json")
                    with open(repaired_event_path, 'w') as f:
                        json.dump(repaired_event_info, f, indent=2, ensure_ascii=False)
                    self.logger.info(f"Saved repaired event to: {repaired_event_path}")

                    self.save_repair_trace()
                    return repaired_event
                else:
                    self.logger.info("Cross page judge failed, continuing exploration...")
                    matched_view = None

            # 4. 没找到目标元素（或 cross page judge 失败），使用 LLM 推荐导航
            self.logger.info(f"Step {self.exploration_step}: Target not found, asking LLM for navigation recommendation...")
            # 重新获取一次 possible_events（scroll 后 view 可能已变化）
            possible_events = self.current_state.get_possible_input(package_name=self.app.get_package_name())
            # 过滤 按照 UIMatch 的规则过滤
            self.logger.info(f"Filtering events: original count = {len(possible_events)}")
            possible_events = self._filter_events_by_rules(possible_events)
            if self.app.get_package_name() == "com.amaze.filemanager" or self.app.get_package_name() == "com.appmindlab.nano":
                possible_events = self.current_state.get_possible_input_only_leaf_nodes(self.app.get_package_name())
            self.logger.info(f"After filtering: {len(possible_events)} events")

            # 4.1 获取 unique views，以及每一个 view 的 event types
            # 用 bounds + class + text + resource_id + content_description 去重
            unique_views = []  # list of views (去重)
            view_event_types = {}  # view_index -> [event_types]
            view_to_events = {}  # view_index -> {event_type: event}

            for event in possible_events:
                if hasattr(event, 'view') and event.view:
                    view = event.view
                    bounds = view.get('bounds', [])
                    view_class = view.get('class', '')
                    text = view.get('text', '')
                    resource_id = view.get('resource_id', '')
                    content_desc = view.get('content_description', '')

                    # 查找是否已存在相同属性的 view
                    existing_idx = None
                    for idx, existing_view in enumerate(unique_views):
                        existing_bounds = existing_view.get('bounds', [])
                        existing_class = existing_view.get('class', '')
                        existing_text = existing_view.get('text', '')
                        existing_resource_id = existing_view.get('resource_id', '')
                        existing_content_desc = existing_view.get('content_description', '')

                        # 所有属性都相同才认为是同一个 widget
                        if (bounds == existing_bounds and
                            view_class == existing_class and
                            text == existing_text and
                            resource_id == existing_resource_id and
                            content_desc == existing_content_desc):
                            existing_idx = idx
                            break

                    # 获取 event type
                    event_type = getattr(event, 'event_type', 'touch')

                    if existing_idx is not None:
                        # view 已存在，添加 event type
                        if event_type not in view_event_types[existing_idx]:
                            view_event_types[existing_idx].append(event_type)
                        view_to_events[existing_idx][event_type] = event
                    else:
                        # 新 view
                        new_idx = len(unique_views)
                        unique_views.append(view)
                        view_event_types[new_idx] = [event_type]
                        view_to_events[new_idx] = {event_type: event}

            self.logger.info(f"Extracted {len(unique_views)} unique views from {len(possible_events)} events")

            # 过滤掉已经访问过的 view + event_type 组合
            current_activity = self.current_state.foreground_activity
            filtered_indices = []
            for idx, view in enumerate(unique_views):
                event_types_for_view = view_event_types.get(idx, [])
                # 检查该 view 的所有 event_type 是否都已访问过
                has_unvisited = False
                for et in event_types_for_view:
                    view_id = self._get_view_navigation_id(view, current_activity, et)
                    if view_id not in self.visited_navigation_elements:
                        has_unvisited = True
                        break
                if has_unvisited:
                    filtered_indices.append(idx)
                else:
                    self.logger.info(f"Filtering out visited element: {view.get('resource_id', '')} {view.get('class', '')}")

            # 重建过滤后的列表
            if len(filtered_indices) < len(unique_views):
                self.logger.info(f"Filtered {len(unique_views) - len(filtered_indices)} visited elements, {len(filtered_indices)} remaining")
                new_unique_views = []
                new_view_event_types = {}
                new_view_to_events = {}
                for new_idx, old_idx in enumerate(filtered_indices):
                    new_unique_views.append(unique_views[old_idx])
                    new_view_event_types[new_idx] = view_event_types[old_idx]
                    new_view_to_events[new_idx] = view_to_events[old_idx]
                unique_views = new_unique_views
                view_event_types = new_view_event_types
                view_to_events = new_view_to_events

            recommended_idx, recommended_event_type = self.llm_recommend_exploration(unique_views, view_event_types, self.exploration_step)

            # 处理 BACK 操作
            if recommended_idx == -1 and recommended_event_type == 'back':
                self.logger.info("LLM recommended BACK action, executing...")
                from .input_event import KeyEvent
                back_event = KeyEvent(name="BACK")
                self.device.send_event(back_event)
                time.sleep(1)

                # 记录 BACK 操作
                new_state = self.device.get_current_state()
                step_info = {
                    'step': self.exploration_step,
                    'action': 'back',
                    'state_after': new_state.state_str if new_state else None,
                    'screenshot': None,  # back 操作不需要截图
                }
                self.repair_trace.append(step_info)

                self.current_state = new_state
                self.exploration_step += 1  # 递增步数
                continue  # 继续下一轮探索

            # 处理 SCROLL_DOWN 操作
            if recommended_idx == -2 and recommended_event_type == 'scroll_down':
                self.logger.info("LLM recommended SCROLL_DOWN action, executing...")

                # 使用 u2 执行向下滚动（从屏幕中下部向上滑动）
                try:
                    self.device.u2.swipe(0.5, 0.7, 0.5, 0.3, duration=0.3)
                    time.sleep(1)
                except Exception as e:
                    self.logger.warning(f"SCROLL_DOWN failed: {e}")

                # 记录 SCROLL_DOWN 操作
                new_state = self.device.get_current_state()
                step_info = {
                    'step': self.exploration_step,
                    'action': 'scroll_down',
                    'state_after': new_state.state_str if new_state else None,
                    'screenshot': None,  # scroll_down 操作不需要截图
                }
                self.repair_trace.append(step_info)

                self.current_state = new_state
                self.exploration_step += 1  # 递增步数
                continue  # 继续下一轮探索

            if recommended_idx is None or recommended_idx < 0 or recommended_idx >= len(unique_views):
                self.logger.warning(f"Invalid LLM recommendation: {recommended_idx}, stopping exploration")
                continue

            # 5. 从 view_to_events 获取对应的 event
            events_for_view = view_to_events.get(recommended_idx, {})
            if recommended_event_type and recommended_event_type in events_for_view:
                event = events_for_view[recommended_event_type]
            elif events_for_view:
                # 使用第一个可用的 event type
                first_type = list(events_for_view.keys())[0]
                event = events_for_view[first_type]
                self.logger.info(f"Event type '{recommended_event_type}' not available, using '{first_type}' instead")
            else:
                self.logger.warning(f"No events found for view index {recommended_idx}")
                continue

            self.logger.info(f"Clicking navigation element [view {recommended_idx}, type {recommended_event_type}]: {event}")

            # 标记该元素 + event_type 为已访问
            # if recommended_idx != -1 and recommended_event_type != 'back':
            #     clicked_view = unique_views[recommended_idx]
            #     clicked_event_type = event.event_type if hasattr(event, 'event_type') else 'touch'
            #     view_id = self._get_view_navigation_id(clicked_view, self.current_state.foreground_activity, clicked_event_type)
            #     self.visited_navigation_elements.add(view_id)
            #     self.logger.info(f"Marked as visited: {view_id}")

            # 记录点击前的 activity
            activity_before = self.current_state.foreground_activity

            self.device.send_event(event)
            time.sleep(1)

            # 6. 获取点击后的新状态
            new_state = self.device.get_current_state()

            # 记录探索阶段的 activity 变化（用于 back navigation 判断）
            activity_after = new_state.foreground_activity if new_state else None
            self.exploration_activity_trace.append({
                'step': self.exploration_step,
                'action': 'navigation',
                'activity_before': activity_before,
                'activity_after': activity_after
            })
            self.logger.info(f"Activity trace: {activity_before} → {activity_after}")

            # 7. 记录导航步骤的 trace
            step_info = {
                'step': self.exploration_step,
                'action': 'navigation',
                'recommended_idx': recommended_idx,
                'event': {
                    'type': event.event_type if hasattr(event, 'event_type') else 'unknown',
                    'view': event.view if hasattr(event, 'view') else None
                },
                'state_after': new_state.state_str if new_state else None,
                'screenshot': os.path.join(self.exploration_tmp_dir, f"states/screen_same_page_{self.exploration_step}.png"),
                'marked_screenshot': os.path.join(self.exploration_tmp_dir, f"images/marked_recommended_step_{self.exploration_step}.png"),
                'xml': os.path.join(self.exploration_tmp_dir, f"xmls/xml_same_page_{self.exploration_step}.xml"),
                'found_target': False,
                'matched_view': None
            }
            self.repair_trace.append(step_info)

            # 8. 保存 navigation event 到文件
            event_info = {
                'tag': f"navigation_step_{self.exploration_step}",
                'event': {
                    'event_type': event.event_type if hasattr(event, 'event_type') else 'touch',
                    'log_lines': None,
                    'x': None,
                    'y': None,
                    'view': event.view if hasattr(event, 'view') else None
                },
                'start_state': self.current_state.state_str if self.current_state else None,
                'stop_state': new_state.state_str if new_state else None,
                'event_str': event.get_event_str(self.current_state) if hasattr(event, 'get_event_str') else str(event)
            }
            event_dir = os.path.join(self.exploration_tmp_dir, "events")
            if not os.path.exists(event_dir):
                os.makedirs(event_dir)
            event_path = os.path.join(event_dir, f"event_navigation_step_{self.exploration_step}.json")
            with open(event_path, 'w') as f:
                json.dump(event_info, f, indent=2, ensure_ascii=False)
            self.logger.info(f"Saved navigation event to: {event_path}")

            # 9. 更新当前状态，递增步数，进入下一轮循环
            self.current_state = new_state
            self.exploration_step += 1

        # 探索完成，没找到目标
        self.logger.warning("Exploration finished, target element not found")
        self.save_repair_trace()
        return None


   


    def _can_back_to_activity(self, target_activity):
        """
        判断是否可以通过 Back 键回到目标 activity

        基于 activity_trace 和 exploration_activity_trace 判断：
        - 如果 target_activity 在当前位置的上游（back stack 中），可以 back
        - 如果 target_activity 在下游或不同分支，无法 back

        Returns:
            (can_back, estimated_back_count): 是否可以 back，预估需要按几次
        """
        current_state = self.device.get_current_state()
        current_activity = current_state.foreground_activity

        # 已经在目标 activity
        if current_activity == target_activity:
            return True, 0

        # 合并 replay 阶段和探索阶段的 activity trace
        all_trace = self.activity_trace + self.exploration_activity_trace

        if not all_trace:
            self.logger.warning("No activity trace available, cannot determine back feasibility")
            return False, 0

        # 在 trace 中找目标 activity 最后出现的位置
        target_idx = -1
        for i in range(len(all_trace) - 1, -1, -1):
            if all_trace[i].get('activity_after') == target_activity:
                target_idx = i
                break

        if target_idx == -1:
            self.logger.info(f"Target activity {target_activity} never appeared in trace, cannot back")
            return False, 0

        # 计算从 target_idx 之后有多少次 activity 变化（这就是需要 back 的次数）
        back_count = 0
        for i in range(target_idx + 1, len(all_trace)):
            before = all_trace[i].get('activity_before')
            after = all_trace[i].get('activity_after')
            if before and after and before != after:
                back_count += 1

        self.logger.info(f"Target activity at trace[{target_idx}], estimated {back_count} backs needed")
        return True, back_count

    def _navigate_back_to_activity(self, target_activity, max_back_presses=10):
        """
        按 Back 键返回，直到回到目标 activity

        先检查是否可以 back（基于 activity graph），不能则直接放弃

        Args:
            target_activity: 目标 activity 名称
            max_back_presses: 最多按几次 Back

        Returns:
            (back_events, success): 返回过程中的事件列表和是否成功
        """
        back_events = []

        # 先检查是否可以 back
        can_back, estimated_count = self._can_back_to_activity(target_activity)
        if not can_back:
            self.logger.warning(f"Cannot back to {target_activity} (not in back stack), giving up")
            return back_events, False

        # 使用预估的 back 次数，但不超过 max_back_presses
        actual_max = min(estimated_count + 2, max_back_presses)  # +2 作为容错
        self.logger.info(f"Trying to back to {target_activity}, estimated {estimated_count} backs, max {actual_max}")

        for i in range(actual_max):
            current_state = self.device.get_current_state()
            current_activity = current_state.foreground_activity

            # 已经在目标 activity
            if current_activity == target_activity:
                self.logger.info(f"✓ Back to {target_activity} after {i} back presses")
                return back_events, True

            # 按 Back 键
            back_event = KeyEvent("BACK")
            self.device.send_event(back_event)
            time.sleep(0.5)

            new_state = self.device.get_current_state()
            back_events.append({
                'action': 'back',
                'step': i,
                'from_activity': current_activity,
                'to_activity': new_state.foreground_activity if new_state else None
            })

            self.logger.info(f"BACK ({i+1}/{actual_max}): {current_activity} → {new_state.foreground_activity if new_state else '?'}")

            # 检查是否退出了应用
            if new_state and new_state.foreground_activity and self.app.package_name not in new_state.foreground_activity:
                self.logger.warning(f"Exited app during back navigation, stopping")
                return back_events, False

        # 最后检查一次
        current_state = self.device.get_current_state()
        current_activity = current_state.foreground_activity
        if current_activity == target_activity:
            self.logger.info(f"✓ Back to {target_activity}")
            return back_events, True

        self.logger.warning(f"Failed to back to {target_activity}, current: {current_activity}")
        return back_events, False

    def llm_recommend_exploration(self, unique_views, view_event_types, step_num, is_has_history = False):
        """
        使用 LLM 推荐最可能隐藏目标元素的组件

        Args:
            unique_views: 去重后的 view 列表
            view_event_types: view_index -> [event_types] 的字典
            step_num: 当前步骤编号

        Returns:
            (recommended_idx, recommended_event_type) 元组，如果失败返回 (None, None)
        """
        try:
            from .UIMatch.utils import (
                read_image, draw_original_element_on_image,
                draw_replay_element_on_image, get_encoded_image, openai_chat
            )

            # 1. 读取原始元素的标记图片（红色框）
            marked_original_path = self.failed_event_png_path.replace(".png", "_marked_original_element.png")
            if not os.path.exists(marked_original_path):
                # 如果不存在，需要生成
                original_element = self._find_original_element(self.failed_event_path, self.failed_event_xml_tree)
                if original_element is None:
                    self.logger.warning("Cannot find original element")
                    return None, None
                original_bounds = self._parse_bounds(original_element.attrib.get("bounds", ""))
                original_img = read_image(self.failed_event_png_path)
                marked_original_img = draw_original_element_on_image(original_img, original_bounds)
                marked_original_img.save(marked_original_path)
            else:
                marked_original_img = read_image(marked_original_path)

            # 2. 在当前页面上标记所有 unique views（绿色框）
            current_screenshot = self.current_state.screenshot_path
            current_img = read_image(current_screenshot)
            current_img_backup = current_img.copy()

            for i, view in enumerate(unique_views):
                bounds = view.get('bounds')
                if bounds:
                    bounds_str = f"[{bounds[0][0]},{bounds[0][1]}][{bounds[1][0]},{bounds[1][1]}]"
                    current_img = draw_replay_element_on_image(current_img, bounds_str, id=i)

            screen_path = os.path.join(self.exploration_tmp_dir, "images")
            if not os.path.exists(screen_path):
                os.makedirs(screen_path)

            # 保存标记后的图片
            marked_candidates_path = os.path.join(screen_path, f"marked_exploration_candidates_step_{step_num}.png")
            current_img.save(marked_candidates_path)

            # 3. 裁剪原始元素图片
            original_element = self._find_original_element(self.failed_event_path, self.failed_event_xml_tree)
            original_bounds = self._parse_bounds(original_element.attrib.get("bounds", ""))
            # 转换为 PIL crop 需要的格式 (x1, y1, x2, y2)
            crop_bounds = (original_bounds[0][0], original_bounds[0][1], original_bounds[1][0], original_bounds[1][1])
            original_full_img = read_image(self.failed_event_png_path)
            original_element_img = original_full_img.crop(crop_bounds)

            # 4. 编码图片
            marked_original_base64 = get_encoded_image(marked_original_img)
            original_element_base64 = get_encoded_image(original_element_img)
            marked_candidates_base64 = get_encoded_image(current_img)

            # 5. 收集之前的操作历史（用于让 LLM 知道哪些路径已经尝试过）
            exploration_history = []
            if is_has_history:
                for trace_step in self.repair_trace:
                    action = trace_step.get('action', '')
                    if action == 'navigation':
                        # 使用已生成的 marked_recommended_image（显示被点击的元素）
                        marked_screenshot_path = trace_step.get('marked_screenshot')
                        if marked_screenshot_path and os.path.exists(marked_screenshot_path):
                            # 获取实际的 event_type（touch, long_touch, set_text 等）
                            event_info = trace_step.get('event', {})
                            event_type = event_info.get('type', 'touch') if isinstance(event_info, dict) else 'touch'
                            self.logger.info(f"Adding history step {trace_step.get('step')}: {marked_screenshot_path}, event_type: {event_type}")
                            step_img = read_image(marked_screenshot_path)
                            exploration_history.append({
                                'step': trace_step.get('step'),
                                'event_type': event_type,
                                'base64': get_encoded_image(step_img)
                            })
                    elif action == 'back':
                        self.logger.info(f"Adding history step {trace_step.get('step')}: BACK action")
                        exploration_history.append({
                            'step': trace_step.get('step'),
                            'event_type': 'back'
                        })
                    elif action == 'scroll_down':
                        self.logger.info(f"Adding history step {trace_step.get('step')}: SCROLL_DOWN action")
                        exploration_history.append({
                            'step': trace_step.get('step'),
                            'event_type': 'scroll_down'
                        })

                self.logger.info(f"Collected {len(exploration_history)} exploration history steps")

            # 6. 构造 prompt（传入 view_event_types 和历史操作）
            system_prompt, user_prompt = self._construct_exploration_llm_prompt(
                marked_original_base64, original_element_base64, marked_candidates_base64,
                view_event_types, exploration_history
            )

            # 7. 调用 LLM
            response, token_usage = openai_chat(system_prompt, user_prompt, self.llm_api_key, "gpt-4.1-mini", "gpt")
            self.logger.info(f"LLM exploration response: {response}")
            self.logger.info(f"Token usage: {token_usage}")

            # 8. 解析返回的组件 ID 和 event type
            import re

            # 首先检查是否返回 [BACK]
            if re.search(r'\[BACK\]', response, re.IGNORECASE):
                self.logger.info("LLM recommended BACK action")
                return -1, 'back'  # 返回 -1 表示 BACK 操作

            if re.search(r'\[SCROLL_DOWN\]', response, re.IGNORECASE):
                self.logger.info("LLM recommended SCROLL_DOWN action")
                return -2, 'scroll_down'  # 返回 -2 表示 SCROLL_DOWN 操作

            # 尝试匹配格式: [index:event_type] 或 [index]
            pattern_with_type = r'\[(\d+):(\w+)\]'
            pattern_simple = r'\[(\d+)\]'

            match_with_type = re.search(pattern_with_type, response)
            match_simple = re.search(pattern_simple, response)

            recommended_idx = None
            recommended_event_type = 'touch'  # 默认为 touch

            if match_with_type:
                recommended_idx = int(match_with_type.group(1))
                recommended_event_type = match_with_type.group(2)
            elif match_simple:
                recommended_idx = int(match_simple.group(1))

            if recommended_idx is not None:
                self.logger.info(f"LLM recommended view index: {recommended_idx}, event_type: {recommended_event_type}")

                # 检查 view index 是否有效
                if recommended_idx >= len(unique_views) or recommended_idx < 0:
                    self.logger.warning("LLM recommended view index out of range, skipping")
                    return None, None

                # 生成 marked_recommended_image
                marked_recommended_image_path = os.path.join(screen_path, f"marked_recommended_step_{step_num}.png")
                view = unique_views[recommended_idx]
                bounds = view.get('bounds')
                if bounds:
                    bounds_str = f"[{bounds[0][0]},{bounds[0][1]}][{bounds[1][0]},{bounds[1][1]}]"
                    current_img_backup = draw_replay_element_on_image(current_img_backup, bounds_str, id=recommended_idx)
                    current_img_backup.save(marked_recommended_image_path)

                return recommended_idx, recommended_event_type
            else:
                self.logger.warning("LLM did not return a valid component index")
                return None, None

        except Exception as e:
            self.logger.error(f"Error in llm_recommend_exploration: {e}")
            import traceback
            traceback.print_exc()
            return None, None

    def _construct_exploration_llm_prompt(self, marked_original_img_base64, original_element_img_base64, marked_replay_img_base64, view_event_types=None, exploration_history=None):
        """
        构造探索推荐的 LLM prompt

        Args:
            view_event_types: 可选，{view_index: [event_types]} 字典
            exploration_history: 可选，之前的操作历史列表
        """

        system_prompt = """
You are an Android developer skilled at analyzing GUI layouts and understanding how UI widgets relate and evolve across different app versions.

In software version iterations, the original target widget may no longer be visible in the updated screen. It may be relocated into a menu, settings page, dialog, drawer, collapsible item, or other UI entry point.

## TASK:
1. Read the original UI information and understand the purpose and meaning of the original widget (marked with red boxes).
2. Read the updated version's screenshot (marked with green boxes showing all clickable UI components).
3. Infer which green-boxed UI widget is the MOST LIKELY ENTRY POINT that the user should click next to reveal or access the target widget.
4. If the potential widget supports multiple interaction types (for example, touch, long_touch), choose the most appropriate one based on the functionality of the original widget.


## GUIDELINES:
1. You are NOT performing similarity matching. You are performing **functional and structural inference** based on UI design conventions.
2. If the current screen is a temporary dialog or blocking screen that prevents accessing the target functionality, you should recommend a BACK action instead of selecting a UI component.


## OUTPUT FORMAT:
Return the most likely UI widget's Number and the recommended interaction type, or explicitly recommend BACK.

EXAMPLE OUTPUT:

```result.md
### Analyze_Process
Explain why the target widget is likely located inside a specific menu or entry point, and describe the reasoning used to choose the best candidate.

### Recommended_UI_No
[18:touch]
OR
[BACK]
```

Note: The format is [index:event_type], where event_type can be touch, long_touch, etc.
If only one action type is available, just use that type.

"""

        analyze_ori_scenarios_prompt = f"""
I will provide you with the original application version's screenshot (marked with red boxes indicating an original UI widget).


* Original Screenshot
```
Please see the above Figure.
```
"""

        analyze_ori_element_prompt = f"""
I will provide you with the original UI widget Figure.

* Original UI widget Figure
```
Please see the above Figure.
```
"""
        # 构建 view event types 描述
        view_info_str = ""
        if view_event_types:
            view_info_str = "\n\n**Available UI Components and their interaction types:**\n"
            for idx in sorted(view_event_types.keys()):
                event_types = view_event_types[idx]
                event_types_str = ", ".join(event_types) if event_types else "touch"
                view_info_str += f"- [{idx}]: available actions: {event_types_str}\n"

        analyze_update_effects_prompt = f"""
I will provide you with the updated application version's screenshot. Different UI components are marked with green boxes and assigned a numerical sequence number.


* Updated Screenshot
```
Please see the above Figure.
```
{view_info_str}
"""



        user_prompt = {}

        user_prompt['ori_analyze'] = [marked_original_img_base64] + [{"type": "text", "text": analyze_ori_scenarios_prompt}] + [original_element_img_base64] + [{"type": "text", "text": analyze_ori_element_prompt}]

        user_prompt['update_analyze'] = [marked_replay_img_base64] + [
            {"type": "text", "text": analyze_update_effects_prompt}
        ]

        # 添加历史操作信息
        if exploration_history and len(exploration_history) > 0:
            history_prompt = f"""
### Previous Exploration History

The following {len(exploration_history)} navigation steps were performed but did not reveal the target element.
Each step shows the UI component that was interacted with and the interaction type.
"""
            history_images = []
            for i, hist in enumerate(exploration_history):
                step = hist.get('step', i)
                event_type = hist.get('event_type', 'touch')
                if event_type == 'back':
                    history_prompt += f"- Step {step}: Pressed BACK button\n"
                else:
                    # 显示实际的操作类型（touch, long_touch, set_text 等）
                    action_desc = {
                        'touch': 'Clicked (touch)',
                        'long_touch': 'Long-pressed',
                        'set_text': 'Set text on'
                    }.get(event_type, f'Interacted ({event_type}) with')
                    history_prompt += f"- Step {step}: {action_desc} a UI component (see History Figure {i+1})\n"
                    if hist.get('base64'):
                        history_images.append(hist['base64'])

            history_prompt += "\nThe green-boxed element in each History Figure shows the element that was interacted with in that step.\n"

            # 将历史图片和文本拼接到 user_prompt['update_analyze']
            user_prompt['update_analyze'] = user_prompt['update_analyze'] + history_images + [
                {"type": "text", "text": history_prompt}
            ]

        return system_prompt, user_prompt

   
    def llm_judge_exploration_success(self, matched_view = None, only_last_screen = False):
        """
        使用 LLM 判断探索是否成功完成了原始功能

        输入：
        - 原始元素标记图（红框标记目标元素）
        - 探索过程中每一步的 marked_clicked 图片（绿框标记点击位置）
        - 最终状态截图
        - matched_view: 可选，如果提供则在当前截图上标记该元素（用于 scroll voting 后的验证）

        输出：
        - True: LLM 认为探索成功完成了原始功能
        - False: LLM 认为探索未能完成原始功能
        """
        try:
            from .UIMatch.utils import (
                read_image, draw_original_element_on_image,
                draw_replay_element_on_image, get_encoded_image, openai_chat
            )

            # 1. 准备原始元素标记图
            marked_original_path = self.failed_event_png_path.replace(".png", "_marked_original_element.png")
            if not os.path.exists(marked_original_path):
                original_element = self._find_original_element(self.failed_event_path, self.failed_event_xml_tree)
                if original_element is None:
                    self.logger.warning("Cannot find original element for judge")
                    return False
                original_bounds = self._parse_bounds(original_element.attrib.get("bounds", ""))
                original_img = read_image(self.failed_event_png_path)
                marked_original_img = draw_original_element_on_image(original_img, original_bounds)
                marked_original_img.save(marked_original_path)
            else:
                marked_original_img = read_image(marked_original_path)

            marked_original_base64 = get_encoded_image(marked_original_img)

            # 2. 裁剪原始元素图片
            original_element = self._find_original_element(self.failed_event_path, self.failed_event_xml_tree)
            if original_element is None:
                self.logger.warning("Cannot find original element for cropping")
                return False
            original_bounds = self._parse_bounds(original_element.attrib.get("bounds", ""))
            # 转换为 PIL crop 需要的格式 (x1, y1, x2, y2)
            crop_bounds = (original_bounds[0][0], original_bounds[0][1], original_bounds[1][0], original_bounds[1][1])
            original_full_img = read_image(self.failed_event_png_path)
            original_element_img = original_full_img.crop(crop_bounds)
            original_element_img_base64 = get_encoded_image(original_element_img)

            # 3. 收集探索过程中每一步的 marked_recommended_image
            exploration_steps_images = []

            for trace_step in self.repair_trace:
                if trace_step.get('action') == 'navigation':
                    # 使用已生成的 marked_recommended_image
                    marked_recommended_image_path = trace_step.get('marked_screenshot')
                    if marked_recommended_image_path and os.path.exists(marked_recommended_image_path):
                        print(f"Adding marked_recommended_image for step {trace_step.get('step')}: {marked_recommended_image_path}")
                        step_img = read_image(marked_recommended_image_path)
                        exploration_steps_images.append({
                            'step': trace_step.get('step'),
                            'base64': get_encoded_image(step_img)
                        })
                        self.logger.info(f"Added marked_recommended_image for step {trace_step.get('step')}: {marked_recommended_image_path}")

            if only_last_screen and len(exploration_steps_images) > 0:
                exploration_steps_images = [exploration_steps_images[-1]]
                self.logger.info(f"Only using last screen for judge")
            
            self.logger.info(f"Collected {len(exploration_steps_images)} exploration steps images for judge")

            # 4. 获取当前页面截图
            current_screenshot_path = self.current_state.screenshot_path
            if current_screenshot_path and os.path.exists(current_screenshot_path):
                current_img = read_image(current_screenshot_path)
            else:
                self.logger.warning("Current screenshot not found")
                return False

            # 5. 如果有 matched_view，标记它作为当前步骤（不管之前有没有探索步骤）
            if matched_view:
                matched_bounds = matched_view.get('bounds', None)
                if matched_bounds:
                    self.logger.info(f"Marking matched_view on current screenshot: bounds={matched_bounds}")
                    # 转换 bounds 格式：[[x1, y1], [x2, y2]] -> "[x1,y1][x2,y2]"
                    if isinstance(matched_bounds, list) and len(matched_bounds) == 2:
                        bounds_str = f"[{matched_bounds[0][0]},{matched_bounds[0][1]}][{matched_bounds[1][0]},{matched_bounds[1][1]}]"
                    else:
                        bounds_str = str(matched_bounds)
                    marked_current_img = draw_replay_element_on_image(current_img.copy(), bounds_str, id="1")
                    # save for debug
                    if not os.path.exists(self.exploration_tmp_dir):
                        os.makedirs(self.exploration_tmp_dir)
                    if not os.path.exists(os.path.join(self.exploration_tmp_dir, "images")):
                        os.makedirs(os.path.join(self.exploration_tmp_dir, "images"))
                    marked_current_img_path = os.path.join(self.exploration_tmp_dir, "images", f"marked_matched_view_step_{self.exploration_step + 1}.png")
                    marked_current_img.save(marked_current_img_path)
                    exploration_steps_images.append({
                        'step': self.exploration_step + 1,
                        'base64': get_encoded_image(marked_current_img)
                    })
                else:
                    self.logger.warning("matched_view has no bounds, using unmarked screenshot")
                    exploration_steps_images.append({
                        'step': self.exploration_step + 1,
                        'base64': get_encoded_image(current_img)
                    })
            elif not exploration_steps_images:
                # 没有 matched_view 且没有之前的探索步骤，用原图
                exploration_steps_images.append({
                    'step': self.exploration_step + 1,
                    'base64': get_encoded_image(current_img)
                })

            # Supplemental information: original next screen
            # 如果 next screen 和 current screen 太相似（>0.9），说明点击后页面没变化，没有信息量
            if self.failed_event_png_next and self.failed_event_png:
                next_current_similarity = compute_ssim(self.failed_event_png, self.failed_event_png_next)
                if next_current_similarity > 0.9:
                    self.logger.info(f"Original next screen is too similar to current screen (similarity={next_current_similarity:.4f} > 0.9), skipping...")
                    original_next_screen_base64 = None
                else:
                    original_next_screen_base64 = get_encoded_image(self.failed_event_png_next)
            elif self.failed_event_png_next:
                original_next_screen_base64 = get_encoded_image(self.failed_event_png_next)
            else:
                original_next_screen_base64 = None
            
            
            # 4. 构造 LLM prompt
            system_prompt, user_prompt = self._construct_judge_exploration_prompt(
                marked_original_base64,
                original_element_img_base64,
                exploration_steps_images,
                original_next_screen_base64
            )

            # 5. 调用 LLM
            response, token_usage = openai_chat(
                system_prompt, user_prompt,
                self.llm_api_key, "gpt-4.1-mini", "gpt"
            )
            self.logger.info(f"LLM judge response: {response}")
            self.logger.info(f"Token usage: {token_usage}")

            # 6. 解析 LLM 返回结果 - 只检查最后一行，避免误匹配文本中的 "Yes or No" 等短语
            last_line = response.strip().split('\n')[-1].upper().strip()
            if last_line == "YES":
                self.logger.info("✓ LLM judged exploration as SUCCESS")
                return True
            elif last_line == "NO":
                self.logger.info("✗ LLM judged exploration as FAILED")
                return False
            else:
                # 如果最后一行不是纯粹的 YES/NO，尝试检查最后一个单词
                last_word = last_line.split()[-1] if last_line.split() else ""
                if last_word == "YES":
                    self.logger.info("✓ LLM judged exploration as SUCCESS")
                    return True
                elif last_word == "NO":
                    self.logger.info("✗ LLM judged exploration as FAILED")
                    return False
                else:
                    self.logger.warning(f"LLM returned ambiguous result: {response}")
                    return False

        except Exception as e:
            self.logger.error(f"Error in llm_judge_exploration_success: {e}")
            import traceback
            traceback.print_exc()
            return False

    def llm_select_best_candidate(self, candidates: dict):
        """
        让 LLM 从所有 candidates 中选择最佳匹配

        输入：
        - 原始元素标记图（红框）
        - 原始元素裁剪图
        - 每个 candidate 的截图（标记位置，用编号 1,2,3...）

        输出：
        - (view_str, candidate_info) 或 None（都不匹配）
        """
        try:
            from .UIMatch.utils import (
                read_image, draw_original_element_on_image,
                draw_replay_element_on_image, get_encoded_image, openai_chat
            )

            if not candidates:
                self.logger.warning("No candidates to select from")
                return None

            # 1. 准备原始元素标记图
            marked_original_path = self.failed_event_png_path.replace(".png", "_marked_original_element.png")
            if not os.path.exists(marked_original_path):
                original_element = self._find_original_element(self.failed_event_path, self.failed_event_xml_tree)
                if original_element is None:
                    self.logger.warning("Cannot find original element for selection")
                    return None
                original_bounds = self._parse_bounds(original_element.attrib.get("bounds", ""))
                original_img = read_image(self.failed_event_png_path)
                marked_original_img = draw_original_element_on_image(original_img, original_bounds)
                marked_original_img.save(marked_original_path)
            else:
                marked_original_img = read_image(marked_original_path)

            marked_original_base64 = get_encoded_image(marked_original_img)

            # 2. 裁剪原始元素图片
            original_element = self._find_original_element(self.failed_event_path, self.failed_event_xml_tree)
            if original_element is None:
                self.logger.warning("Cannot find original element for cropping")
                return None
            original_bounds = self._parse_bounds(original_element.attrib.get("bounds", ""))
            crop_bounds = (original_bounds[0][0], original_bounds[0][1], original_bounds[1][0], original_bounds[1][1])
            original_full_img = read_image(self.failed_event_png_path)
            original_element_img = original_full_img.crop(crop_bounds)
            original_element_img_base64 = get_encoded_image(original_element_img)

            # 3. 为每个 candidate 生成标记截图
            candidates_list = list(candidates.items())
            candidates_images = []

            for idx, (view_str, candidate_info) in enumerate(candidates_list, start=1):
                view = candidate_info['view']
                last_state = candidate_info.get('last_state')

                if last_state and last_state.screenshot_path and os.path.exists(last_state.screenshot_path):
                    screenshot_img = read_image(last_state.screenshot_path)
                else:
                    self.logger.warning(f"Candidate {idx} has no valid screenshot, skipping")
                    continue

                # 获取 candidate 的 bounds
                bounds = view.get('bounds', [[0, 0], [100, 100]])
                if isinstance(bounds, list) and len(bounds) == 2:
                    bounds_tuple = (bounds[0][0], bounds[0][1], bounds[1][0], bounds[1][1])
                else:
                    bounds_tuple = bounds

                # 在截图上标记 candidate 位置
                marked_img = draw_replay_element_on_image(screenshot_img, bounds_tuple, idx)
                marked_img_base64 = get_encoded_image(marked_img)

                # 保存标记后的图片用于调试
                marked_img_path = os.path.join(
                    self.exploration_tmp_dir, "states",
                    f"candidate_{self.failed_event_number}_{idx}.png"
                )
                marked_img.save(marked_img_path)

                candidates_images.append({
                    'index': idx,
                    'view_str': view_str,
                    'image_base64': marked_img_base64,
                    'matching_method': candidate_info.get('matching_method', 'unknown'),
                    'count': candidate_info.get('count', 1),
                    'text': view.get('text') or view.get('content_description') or '',
                    'bounds': bounds,
                    'class': view.get('class', ''),
                    'resource_id': view.get('resource_id', '')
                })

            if not candidates_images:
                self.logger.warning("No valid candidate images generated")
                return None

            # 4. 构造 prompt
            system_prompt, user_prompt = self._construct_select_candidate_prompt(
                marked_original_base64,
                original_element_img_base64,
                candidates_images
            )

            # 5. 调用 LLM
            response, token_usage = openai_chat(
                system_prompt, user_prompt,
                self.llm_api_key, "gpt-4.1-mini", "gpt"
            )
            self.logger.info(f"LLM select candidate response: {response}")
            self.logger.info(f"Token usage: {token_usage}")

            # 6. 解析 LLM 返回结果
            response_upper = response.upper()

            # 检查是否返回 NONE
            if "NONE" in response_upper:
                self.logger.info("LLM selected NONE - no matching candidate")
                return None

            # 尝试提取 CANDIDATE_N
            import re
            match = re.search(r'CANDIDATE[_\s]*(\d+)', response_upper)
            if match:
                selected_idx = int(match.group(1))
                if 1 <= selected_idx <= len(candidates_images):
                    selected_view_str = candidates_images[selected_idx - 1]['view_str']
                    selected_candidate = candidates[selected_view_str]
                    self.logger.info(f"✓ LLM selected CANDIDATE_{selected_idx}: {selected_view_str[:30]}...")
                    return (selected_view_str, selected_candidate)
                else:
                    self.logger.warning(f"LLM returned invalid index: {selected_idx}, max is {len(candidates_images)}")
                    return None
            else:
                self.logger.warning(f"LLM returned unparseable result: {response}")
                return None

        except Exception as e:
            self.logger.error(f"Error in llm_select_best_candidate: {e}")
            import traceback
            traceback.print_exc()
            return None

    def _construct_select_candidate_prompt(self, marked_original_base64, original_element_img_base64, candidates_images):
        """
        构造让 LLM 选择最佳 candidate 的 prompt
        格式需要符合 openai_chat 函数的要求：{'ori_analyze': [...], 'update_analyze': [...]}
        """
        system_prompt = """
You are an Android UI analysis expert with experience in UI evolution across app versions.
Your task is to select the best matching candidate on the updated app version corresponds to the original UI widget from the old version.

## Key Rules
1. Focus on FUNCTIONALITY, not just appearance
2. The selected element should be able to perform the exact same action as the original
3. Consider: text content, content description, element type, and position
4. If NO candidate matches the original element's function, answer NONE

## Output Format
Provide a brief reasoning, then output ONLY one of:
CANDIDATE_1
CANDIDATE_2
...
CANDIDATE_N
or
NONE
"""

        # ori_analyze: 原始元素的信息
        ori_analyze_text = """
I will provide you with the original application version's screenshot (marked with red box indicating the target UI element) and the cropped original UI element.

* Original Screenshot (with target element marked in red box)
```
please see Figure 1.
```

* Original UI Element (cropped)
```
please see Figure 2.
```
"""
        ori_analyze = [
            marked_original_base64,
            original_element_img_base64,
            {"type": "text", "text": ori_analyze_text}
        ]

        # update_analyze: 候选元素的信息
        candidates_text = f"""
I will provide you with {len(candidates_images)} candidate elements found during scroll exploration. Each candidate is marked with a green box and labeled with an index number.

Your task is to determine which candidate element (if any) can perform the SAME FUNCTION as the original target element.

## Candidate Elements:
"""
        for candidate in candidates_images:
            idx = candidate['index']
            candidates_text += f"""
### CANDIDATE_{idx}:
(See corresponding image below)
"""

        candidates_text += """
## Question:
Which candidate element best matches the original element's FUNCTION? Select the one that can perform the same action.
If none of the candidates match, answer NONE.

Answer format: CANDIDATE_1 / CANDIDATE_2 / ... / NONE
"""

        # 构造 update_analyze: 所有候选图片 + 文本描述
        update_analyze = []
        for candidate in candidates_images:
            update_analyze.append(candidate['image_base64'])
        update_analyze.append({"type": "text", "text": candidates_text})

        user_prompt = {
            'ori_analyze': ori_analyze,
            'update_analyze': update_analyze
        }

        return system_prompt, user_prompt

#     def _construct_judge_exploration_prompt(self, marked_original_base64, original_element_img_base64, exploration_steps_images):

#         system_prompt = """
# You are an Android UI testing expert.

# Your task is to determine whether the FINAL screen reached by the exploration already allows the user to EXECUTE the intended function of the original UI element, without requiring any further navigation.

# IMPORTANT:
# - Base your judgment ONLY on the FINAL screen.
# - Exploration history is provided ONLY to understand the user's intent.
# - Do NOT assume a function is completed just because a related menu item or page title is visible.

# ## How to Judge Completion

# First, understand the FUNCTION of the original UI element (red-boxed). Then decide whether the FINAL screen satisfies the following:

# ### Function Completion Rule

# A function is considered COMPLETED ONLY IF:

# 1. The FINAL screen directly presents the control where the user can perform the intended action or change the intended value.

# 2. The user can complete the action on the FINAL screen using visible controls (e.g., input field + confirm button, option list, switch).

# 3. No additional click is required to reveal the actual execution interface.

# ### NOT Completed If:

# - The FINAL screen only shows an entry, menu item, or label that leads to the action.
# - The FINAL screen shows a related operation (e.g., "Create" instead of "Rename").
# - The FINAL screen shows a dialog or page title, but the actual editable or actionable control is not visible.

# Operation context (page titles, dialog titles, button labels) may be used ONLY to reject mismatched operations, not to infer completion.

# ## Output Format

# Provide a brief explanation (optional), then output ONLY:

# YES
# or
# NO
#     """

#         original_block = """
# ## Original Target Element
# Below is the screenshot of the original UI containing the target element (red box), followed by a zoomed-in figure of that element.

# Identify the FUNCTION TYPE of this element and understand what kind of user action it enables.
#     """

#         user_prompt = {}
#         user_prompt["ori_analyze"] = [
#             marked_original_base64,
#             original_element_img_base64,
#             {"type": "text", "text": original_block},
#         ]

#         steps_block = f"""
# ## Exploration Steps
# These images show the navigation path. Each step highlights the clicked UI element in green.

# Total steps: {len(exploration_steps_images)}
# Steps are in order from step 0 to step {len(exploration_steps_images) - 1}.
# Your final judgment must be based on the LAST SCREEN.
#     """

#         exploration_imgs = [step["base64"] for step in exploration_steps_images]

#         user_prompt["update_analyze"] = exploration_imgs + [
#             {"type": "text", "text": steps_block}
#         ]

#         question_text = """
# ## Final Question
# Based on the widget type and unified rules, did the exploration successfully reach a screen where the SAME FUNCTION as the original UI element can be performed?

# Answer strictly with:

# YES
# or
# NO
#     """

#         user_prompt["question"] = [{"type": "text", "text": question_text}]

#         return system_prompt, user_prompt


#     def _construct_judge_exploration_prompt(self, marked_original_base64, original_element_img_base64, exploration_steps_images):

#         system_prompt = """
# You are an Android UI testing expert. You are working on UI evolution analysis across app versions. Your task is to determine whether, in the NEW version of the app, the FINAL screen selected a UI component that is functionally and semantically equivalent to the original target UI element from the OLD version.

# Judgment rules:
# - Judge ONLY based on UI elements that are visibly marked with a green box on the FINAL screen.
# - You MAY use the PREVIOUS screen as contextual information to understand the role and meaning of the currently selected UI component.
# - Two UI components are equivalent ONLY IF they represent the same operation intent (e.g., create, modify, select, navigate), operate on the same target (e.g., existing object vs new object), and are in the same execution state (entry-only vs directly executable). Visual similarity or identical control types alone are NOT sufficient.


# ### Output format:
# ```result.md
# ### Analyze_Process
# (Provide a brief explanation (1–3 sentences))
# Then output ONLY:

# YES
# or
# NO
#     """

#         original_block = """
# ## Original Target Element
# Below is the screenshot of the original UI containing the target element (red box), followed by a zoomed-in figure of that element.

# Identify what this UI element represents and what role it plays from the user's perspective (e.g., a button, menu entry, toggle, text field).
#     """

#         user_prompt = {}
#         user_prompt["ori_analyze"] = [
#             marked_original_base64,
#             original_element_img_base64,
#             {"type": "text", "text": original_block},
#         ]

#         steps_block = f"""
# ## Exploration Steps
# These images show the navigation path including the LAST and FINAL screens. Each screen highlights the clicked UI element in green.
#     """

#         exploration_imgs = [step["base64"] for step in exploration_steps_images]

#         user_prompt["update_analyze"] = exploration_imgs + [
#             {"type": "text", "text": steps_block}
#         ]

#         question_text = """
# ## Final Question
# Does the FINAL screen contain a green-boxed UI component that is equivalent to the original target UI element?

# Answer strictly with:

# YES
# or
# NO
#     """

#         user_prompt["question"] = [{"type": "text", "text": question_text}]

#         return system_prompt, user_prompt


# Jan 7, 81% success rate
    def _construct_judge_exploration_prompt(self, marked_original_base64, original_element_img_base64, exploration_steps_images, original_next_screen_base64 = None):

        """
        增加了一个original_next_screen_base64，用于提供原始的下一个屏幕截图
        """

        system_prompt = """
You are an Android UI testing expert. You are working on UI evolution analysis across app versions.
Your task is to determine whether the current exploration trace has already reached a screen where the user is positioned to perform the SAME FUNCTION as the original UI element in the OLD version.

# ===============================
# 1. Widget Type Classification
# ===============================

You MUST classify BOTH:
- the original UI element (red-boxed) in the OLD version, AND
- the selected UI element (green-boxed) on the FINAL SCREEN in the NEW version
into exactly ONE of the following categories, based on their semantic role.

### (A) ENTRY-TYPE WIDGET (Navigation Control)
Examples: “More Options” (⋮), menu items, page entries, list items, buttons whose purpose is to navigate into another screen.
Function characteristics:
- Its purpose is to OPEN another page / dialog / menu.
- It does NOT directly change a value.

### (B) TERMINAL-READONLY WIDGET
Examples: labels displaying current state, informational text, static indicators without user interaction.
Function characteristics:
- Displays information but cannot change it.

### (C) TERMINAL-EDITABLE WIDGET (Actionable Setting)
Examples: switch, checkbox, radio option, editable text field, dialog with selectable options.
Function characteristics:
- Allows directly changing a value or selecting an option.

You may use the provided "Original Next Screen" (if available) as supporting evidence to determine the original UI element's type.

# ===============================
# 2. Success Judgment Rules
# ===============================

Judge success according to the widget type of the original UI element and the selected UI element on the FINAL SCREEN and the following rules:

First, their widget types must be the SAME.

Then, judge success as follows:

- ENTRY-TYPE:
  SUCCESS if a functionally equivalent entry to the same interaction flow intent and page level context is visible on the final screen.
  Differences in visual form (icon vs menu item), placement, or presentation style do NOT affect equivalence.

- TERMINAL-READONLY:
  SUCCESS if the same information (or its clear equivalent) is visible on the final screen.

- TERMINAL-EDITABLE:
  SUCCESS if the corresponding editable control (e.g., switch, checkbox, radio options, or option dialog) is visible and directly reachable on the final screen.


IMPORTANT:
Do NOT assume that a configurable option is editable unless an explicit control (e.g., switch, checkbox, radio buttons, or a visible option dialog) is present on the screen.
A text row or list item that requires another tap to open a sub-screen or dialog is NOT considered editable.


# ===============================
# Output Format (STRICT)
# ===============================

Provide a brief explanation (1–3 sentences), then output ONLY:

YES
or
NO
    """

        original_block = """
## Original Target Element
Below is the screenshot of the original UI element (red box), followed by a zoomed-in figure of that element in the OLD version.

Identify the semantic meaning of this element in the OLD version and understand what kind of user action it enables, regardless of visual form.
    """

        user_prompt = {}
        user_prompt["ori_analyze"] = [
            {"type": "text", "text": original_block},
            marked_original_base64,
            original_element_img_base64
        ]

        if original_next_screen_base64:
            original_next_screen_block = """
## Original Next Screen
Below is the screenshot of the screen reached in the OLD version immediately AFTER interacting with the original UI element.

Use this screen to infer the semantic meaning of the ORIGINAL UI element, especially when the original icon or label is abstract, by leveraging the resulting screen’s title and content.
            """
            
            
            user_prompt["ori_analyze"].append({"type": "text", "text": original_next_screen_block})
            user_prompt["ori_analyze"].append(original_next_screen_base64)

        steps_block = f"""
## Exploration Steps
These images show the navigation path in the NEW version. Each step highlights the UI element that was operated at that step (green box).

Total steps: {len(exploration_steps_images)}
Steps are in order from step 0 to step {len(exploration_steps_images) - 1}.
Your final judgment MUST be based ONLY on what is explicitly visible on the FINAL SCREEN and the exploration steps. Do NOT assume any additional screens, dialogs, or interactions.
    """

        user_prompt["update_analyze"] = [
            {"type": "text", "text": steps_block}
        ] + [step["base64"] for step in exploration_steps_images]

        question_text = """
## Final Question
Based on your analysis, has the exploration already reached a screen where the user is positioned to perform the SAME FUNCTION as the original UI element in the OLD version, without assuming any additional screens or interactions?

Answer strictly with:

YES
or
NO
    """
    # 将 question 拼接到 user_prompt["update_analyze"] 后面
        user_prompt["update_analyze"] = user_prompt["update_analyze"] + [{"type": "text", "text": question_text}]

        return system_prompt, user_prompt


#     def _construct_judge_exploration_prompt(self, marked_original_base64, original_element_img_base64, exploration_steps_images, original_next_screen_base64 = None):

#         """
#         增加了一个original_next_screen_base64，用于提供原始的下一个屏幕截图
#         """

#         system_prompt = """
# You are an Android UI testing expert. 

# Your task is to determine whether the selected UI component on the final screen reached by a sequence of exploration steps allows the user to perform the SAME FUNCTION as the original UI element.

# ## JUDGMENT RULES
# 1) Classify the original target element into exactly ONE type:
# (A) ENTRY-TYPE: opens another page/menu/dialog; does not change a value directly.
# (B) TERMINAL-READONLY: shows information only; not editable.
# (C) TERMINAL-EDITABLE: directly changes a value or selects an option (switch/checkbox/radio/text field/option dialog).

# 2) Type consistency (HARD RULE):
# The equivalent component MUST be the SAME type as the original.
# If types mismatch → answer NO.

# 3) Success rule (based on the SELECTED component on the FINAL screen):
# - If original is ENTRY-TYPE:
#   YES only if the selected component is an ENTRY that starts the same flow.
# - If original is TERMINAL-READONLY:
#   YES only if the same information is visible on the final screen.
# - If original is TERMINAL-EDITABLE:
#   YES only if the selected component is directly actionable on the final screen to change the value / choose the option.
#   If the selected component is only an entry that requires another click to reach the editable control/options → NO.


# ## OUTPUT FORMAT (STRICT)

# Provide a brief explanation (1–3 sentences), then output ONLY:

# YES
# or
# NO
#     """

#         original_block = """
# ## Original Target Element
# Below is the screenshot of the original UI containing the target element (red box), followed by a zoomed-in figure of that element.

# Identify the FUNCTION TYPE of this element and understand what kind of user action it enables.
#     """

#         user_prompt = {}
#         user_prompt["ori_analyze"] = [
#             {"type": "text", "text": original_block},
#             marked_original_base64,
#             original_element_img_base64
#         ]

#         if original_next_screen_base64:
#             original_next_screen_block = """
# ## Original Next Screen
# Below is the screenshot of the screen reached in the OLD version immediately AFTER interacting with the original target element.

# Infer the true function of the original target element.
#             """
            
            
#             user_prompt["ori_analyze"].append({"type": "text", "text": original_next_screen_block})
#             user_prompt["ori_analyze"].append(original_next_screen_base64)

#         steps_block = f"""
# ## Exploration Steps
# These images show the navigation path. Each step highlights the clicked UI element in green.

# Total steps: {len(exploration_steps_images)}
# Steps are in order from step 0 to step {len(exploration_steps_images) - 1}.
# Your final judgment must be based on the FINAL SCREEN.
#     """

#         user_prompt["update_analyze"] = [
#             {"type": "text", "text": steps_block}
#         ] + [step["base64"] for step in exploration_steps_images]

#         question_text = """
# ## Final Question
# Based on the widget type and unified rules, did the exploration successfully reach a screen where the SAME FUNCTION as the original UI element can be performed?

# Answer strictly with:

# YES
# or
# NO
#     """

#         # 将 question 拼接到 user_prompt["update_analyze"] 后面
#         user_prompt["update_analyze"] = user_prompt["update_analyze"] + [{"type": "text", "text": question_text}]

#         return system_prompt, user_prompt


#     def _construct_judge_exploration_prompt(self, marked_original_base64, original_element_img_base64, exploration_steps_images, original_next_screen_base64 = None):

#         """
#         增加了一个original_next_screen_base64，用于提供原始的下一个屏幕截图
#         """

#         system_prompt = """
# You are an Android UI testing expert judging whether an exploration successfully replicated a UI function.

# ## Success Criteria

# The exploration is successful if the FINAL SCREEN satisfies ONE of:

# 1. **Same action is available**: The user can perform the identical operation (e.g., toggle the same setting, click the same menu entry)

# 2. **Same outcome is reachable**: The user is one obvious step away from the same outcome (e.g., a dialog is open with the relevant option visible)

# 3. **Same information is displayed**: For read-only elements, the equivalent  information is visible

# ## Key Principle

# Focus on WHAT THE USER CAN ACHIEVE, not on how the UI is structured. Version updates may reorganize UI while preserving function.


# ## Output Format

# Provide a brief explanation (1–3 sentences), then output ONLY:

# YES
# or
# NO
#     """

#         original_block = """
# ## Original Target Element
# Below is the screenshot of the original UI containing the target element (red box), followed by a zoomed-in figure of that element.

# Identify the FUNCTION TYPE of this element and understand what kind of user action it enables.
#     """

#         user_prompt = {}
#         user_prompt["ori_analyze"] = [
#             {"type": "text", "text": original_block},
#             marked_original_base64,
#             original_element_img_base64
#         ]

#         if original_next_screen_base64:
#             original_next_screen_block = """
# ## Original Next Screen
# Below is the screenshot of the screen reached in the OLD version immediately AFTER interacting with the original target element.

# Infer the true function of the original target element.
#             """
            
            
#             user_prompt["ori_analyze"].append({"type": "text", "text": original_next_screen_block})
#             user_prompt["ori_analyze"].append(original_next_screen_base64)

#         steps_block = f"""
# ## Exploration Steps
# These images show the navigation path. Each step highlights the clicked UI element in green.

# Total steps: {len(exploration_steps_images)}
# Steps are in order from step 0 to step {len(exploration_steps_images) - 1}.
# Your final judgment must be based on the FINAL SCREEN.
#     """

#         user_prompt["update_analyze"] = [
#             {"type": "text", "text": steps_block}
#         ] + [step["base64"] for step in exploration_steps_images]

#         question_text = """
# ## Final Question
# Based on the widget type and unified rules, did the exploration successfully reach a screen where the SAME FUNCTION as the original UI element can be performed?

# Answer strictly with:

# YES
# or
# NO
#     """

#         # 将 question 拼接到 user_prompt["update_analyze"] 后面
#         user_prompt["update_analyze"] = user_prompt["update_analyze"] + [{"type": "text", "text": question_text}]

#         return system_prompt, user_prompt

#     def _construct_judge_exploration_prompt(self, marked_original_base64, original_element_img_base64, exploration_steps_images, original_next_screen_base64 = None):

#         system_prompt = """
# You are an Android UI testing expert. Your task is to determine whether the final screen reached by a sequence of exploration steps allows the user to perform the SAME FUNCTION as the original UI element.

# # ===============================
# # 1. Classify the Original UI Element Into One of Three Types
# # ===============================

# Before judging success, identify which category the original UI element belongs to:

# ### (A) ENTRY-TYPE WIDGET (Navigation Control)
# Examples: “More Options” (⋮), menu items, page entries, list items, buttons whose purpose is to navigate into another screen.
# Function characteristics:
# - Its purpose is to OPEN another page / dialog / menu.
# - It does NOT directly change a value.
# Success condition:
# - Final screen should show the SAME ENTRY POINT (or an equivalent navigation destination), OR
# - The exploration already reached the destination that this entry leads to.

# ### (B) TERMINAL-READONLY WIDGET
# Examples: labels displaying current state, informational text, static indicators without user interaction.
# Function characteristics:
# - Displays information but cannot change it.
# Success condition:
# - Final screen presents the SAME INFORMATIONAL CONTENT or equivalent representation.

# ### (C) TERMINAL-EDITABLE WIDGET (Actionable Setting)
# Examples: switch, checkbox, radio option, editable text field, dialog with selectable options.
# Function characteristics:
# - Allows directly changing a value or selecting an option.
# Success condition:
# - The final screen must present the SAME SETTING CONTROL and allow direct modification of the value.

# # ===============================
# # 2. Unified Judgment Rule
# # ===============================

# After understanding the original widget type:

# - If it is ENTRY-TYPE → success if the same entry exists OR its destination page is reached.
# - If it is TERMINAL-READONLY → success if the same information is visible.
# - If it is TERMINAL-EDITABLE → success only if the corresponding editable control is present and actionable on the final screen.

# IMPORTANT:
# Do NOT require all widgets to be actionable.
# Do NOT assume the original control is always a setting.
# Base your reasoning strictly on the FUNCTION implied by the widget type.

# # ===============================
# # Output Format
# # ===============================

# Provide a brief explanation (1–3 sentences), then output ONLY:

# YES
# or
# NO
#     """

#         original_block = """
# ## Original Target Element
# Below is the screenshot of the original UI containing the target element (red box), followed by a zoomed-in figure of that element.

# Identify the FUNCTION TYPE of this element and understand what kind of user action it enables.
#     """

#         user_prompt = {}
#         user_prompt["ori_analyze"] = [
#             marked_original_base64,
#             original_element_img_base64,
#             {"type": "text", "text": original_block},
#         ]

#         steps_block = f"""
# ## Exploration Steps
# These images show the navigation path. Each step highlights the clicked UI element in green.

# Total steps: {len(exploration_steps_images)}
# Steps are in order from step 0 to step {len(exploration_steps_images) - 1}.
# Your final judgment must be based on the FINAL SCREEN.
#     """

#         exploration_imgs = [step["base64"] for step in exploration_steps_images]

#         user_prompt["update_analyze"] = exploration_imgs + [
#             {"type": "text", "text": steps_block}
#         ]

#         question_text = """
# ## Final Question
# Based on the widget type and unified rules, did the exploration successfully reach a screen where the SAME FUNCTION as the original UI element can be performed?

# Answer strictly with:

# YES
# or
# NO
#     """

#         user_prompt["question"] = [{"type": "text", "text": question_text}]

#         return system_prompt, user_prompt




    def _create_repaired_event(self, matched_view):
        """
        创建修复后的事件

        Args:
            matched_view: 匹配到的 view 字典

        Returns:
            TouchEvent: 修复后的点击事件
        """
        # 记录这次匹配的 view，用于后续反馈机制
        self.last_repaired_view = matched_view

        repaired_event = TouchEvent(view=matched_view)
        # repaired_event.u2 = self.device.u2
        self.mode = "replay"  # 切回回放模式
        return repaired_event

    def filter_scroll_events(self, scrollable_events):
        """
        从所有scrollable_events中过滤出可用的scroll_events

        处理逻辑：
        1. 收集唯一的scrollable view（通过view_str去重）
        2. 根据view的宽高比决定滚动方向
        3. 对覆盖的scrollable view
          - 如果方向是一样的，并且两个scrollable view相交的面积大于小的view的80%，认为小的可以去掉
          - 如果方向不一样，两个都保留

        Args:
            scrollable_events: 原始的scrollable事件列表

        Returns:
            过滤后的scroll_events列表
        """
        def bounds_overlap(bounds1, bounds2, overlap_threshold=0.8):
            """检测两个矩形是否显著重叠（阈值80%）"""
            x1_min, y1_min = bounds1[0]
            x1_max, y1_max = bounds1[1]
            x2_min, y2_min = bounds2[0]
            x2_max, y2_max = bounds2[1]

            # 先检查是否有任何重叠
            if x1_max <= x2_min or x2_max <= x1_min or y1_max <= y2_min or y2_max <= y1_min:
                return False

            # 计算重叠区域
            overlap_x_min = max(x1_min, x2_min)
            overlap_y_min = max(y1_min, y2_min)
            overlap_x_max = min(x1_max, x2_max)
            overlap_y_max = min(y1_max, y2_max)
            overlap_area = (overlap_x_max - overlap_x_min) * (overlap_y_max - overlap_y_min)

            # 计算两个矩形的面积
            area1 = (x1_max - x1_min) * (y1_max - y1_min)
            area2 = (x2_max - x2_min) * (y2_max - y2_min)
            smaller_area = min(area1, area2)

            # 只有重叠面积超过较小矩形的80%才算重叠
            if smaller_area > 0 and overlap_area / smaller_area >= overlap_threshold:
                return True
            return False

        def get_scroll_direction(view, events):
            """
            根据view的class决定滚动方向

            - HorizontalScrollView → 只尝试 'right'
            - 其他 → 优先 'down'，再尝试 'right'

            Returns:
                (direction, event): 滚动方向和对应的event，如果没有对应方向的event返回(None, None)
            """
            view_class = view.get('class', '') if view else ''

            if 'HorizontalScrollView' in view_class:
                directions = ['right']
            else:
                directions = ['down', 'right']

            for direction in directions:
                if direction in events:
                    self.logger.info(f"View class={view_class}, using direction='{direction}'")
                    return direction, events[direction]

            return None, None

        # 1. 收集所有唯一的scrollable view对象（通过view_str去重）
        scrollable_views = {}  # {view_str: {'view': view, 'events': {direction: event}}}
        for event in scrollable_events:
            view = event.view
            if view:
                view_str = view.get('view_str', str(view.get('bounds', '')))
                if view_str not in scrollable_views:
                    scrollable_views[view_str] = {'view': view, 'events': {}}
                scrollable_views[view_str]['events'][event.direction] = event

        self.logger.info(f"Found {len(scrollable_views)} unique scrollable views")

        # 2. 测试每个view的实际滚动方向，收集有效的滚动事件
        # [(view_str, view, direction, event, bounds, area)]
        valid_scroll_views = []
        for view_str, view_data in scrollable_views.items():
            view = view_data['view']
            events = view_data['events']

            # 根据宽高比决定滚动方向
            direction, scroll_event = get_scroll_direction(view, events)

            if direction is None:
                self.logger.info(f"Skipping view {view_str}: no valid scroll direction")
                continue

            if 'bounds' in view:
                bounds = view['bounds']
                view_width = bounds[1][0] - bounds[0][0]
                view_height = bounds[1][1] - bounds[0][1]
                view_area = view_width * view_height
                valid_scroll_views.append((view_str, view, direction, scroll_event, bounds, view_area))
                self.logger.info(f"Valid scroll view: direction={direction}, size={view_width}x{view_height}")
            else:
                valid_scroll_views.append((view_str, view, direction, scroll_event, None, 0))

        # 3. 去除重叠的views（同方向保留面积大的，不同方向都保留）
        unique_views = []
        for item in valid_scroll_views:
            view_str, view, direction, scroll_event, bounds, area = item
            if bounds is None:
                unique_views.append(item)
                continue

            should_add = True
            for i, existing_item in enumerate(unique_views):
                existing_bounds = existing_item[4]
                existing_direction = existing_item[2]

                if existing_bounds and bounds_overlap(bounds, existing_bounds):
                    # 方向不同，两个都保留
                    if direction != existing_direction:
                        self.logger.info(f"Keeping both overlapping views: different scroll direction ({direction} vs {existing_direction})")
                        continue

                    # 方向相同，保留面积大的
                    existing_area = existing_item[5]
                    if area > existing_area:
                        self.logger.info(f"Replacing overlapping view: new area {area} > existing {existing_area}")
                        unique_views[i] = item
                    else:
                        self.logger.info(f"Skipping overlapping view: area {area} <= existing {existing_area}")
                    should_add = False
                    break

            if should_add:
                unique_views.append(item)

        # 4. 返回过滤后的scroll events
        scroll_events = []
        for view_str, view, direction, scroll_event, bounds, area in unique_views:
            scroll_events.append(scroll_event)
            self.logger.info(f"Added scroll {direction} event for view")

        return scroll_events

    def find_target_element_in_page(self, current_state, step, cross_page=False):
        """
        在当前页面中使用UIMatch算法查找目标元素

        Args:
            current_state: 当前设备状态

        Returns:
            (matched_view, matching_method): 成功匹配的view字典和匹配方法，或 (None, None)
        """
        try:
            # 使用已经加载的失败事件数据
            if self.failed_event_json is None or self.failed_event_xml_tree is None:
                self.logger.error("Failed event data not loaded")
                return None, None

            # 在失败事件的 XML 中找到目标元素
            original_element = self._find_original_element(self.failed_event_path, self.failed_event_xml_tree)

            if original_element is None:
                self.logger.warning("Target element not found in original XML")
                return None, None

            # 当前状态的XML和截图，保存到exploration_tmp目录
            current_state.tag = f"same_page_{step}"
            state_dir = os.path.join(self.exploration_tmp_dir, "states")
            current_state.save2dir(state_dir)
            current_xml_path = os.path.join(self.exploration_tmp_dir, f"xmls/xml_same_page_{step}.xml")
            current_png_path = os.path.join(self.exploration_tmp_dir, f"states/screen_same_page_{step}.png")

            # 解析当前XML
            with open(current_xml_path, 'r', encoding='utf-8') as f:
                current_xml_tree = ET.parse(f)

            matcher = Matcher(
                original_png=self.failed_event_png_path,
                original_tree=self.failed_event_xml_tree,
                original_element=original_element,
                replay_png=current_png_path,
                replay_tree=current_xml_tree,
                logger=self.logger,
                cross_page=cross_page
            )

            # 执行匹配
            matching_result = matcher.matching(app_name=self.app.get_package_name())

            if matching_result.get("success"):
                matched_element = matching_result.get("matched_element")
                matching_method = matching_result.get('matching_method', 'unknown')
                self.logger.info(f"✓ Found target element using {matching_method} matching")

                # using the matched element to replace the event
                for current_view in current_state.views:
                    # normalize
                    resource_id = self.normalize(current_view['resource_id'])
                    text = self.normalize(current_view['text']) #可能会变
                    content_description = self.normalize(current_view['content_description'])
                    class_name = self.normalize(current_view['class'])
                    bounds = current_view['bounds']

                    if self.check_if_same(resource_id, matched_element.get('resource-id')) and \
                    self.check_if_same(content_description, matched_element.get('content-desc')) and \
                    self.check_if_same(class_name, matched_element.get('class')) and \
                    self.compare_bounds(bounds, matched_element.get('bounds')):

                        # 检查是否在排除列表中
                        if self._is_view_excluded(current_view):
                            self.logger.info(f"Skipping excluded view: {current_view.get('view_str', 'unknown')}")
                            continue

                        return current_view, matching_method

                # 如果没找到匹配的 view，返回 None
                self.logger.warning("Matched element not found in current_state.views")
                return None, None
            else:
                self.logger.info("Target element not found in current page")
                return None, None

        except Exception as e:
            self.logger.error(f"Error in find_target_element_in_page: {e}")
            import traceback
            traceback.print_exc()
            return None, None


    def _find_original_element(self, event_path, xml_tree) -> ET.Element:
        """
        根据event中的信息，在xml_tree中找到对应的元素
        
        Args:
            event_path: 事件文件路径
            xml_tree: XML树对象
            
        Returns:
            找到的元素对象或者none
        """
        import json
        
        # 1. 从事件文件中提取bounds和class信息
        try:
            with open(event_path, 'r', encoding='utf-8') as f:
                event = json.load(f)
            
            # 提取目标bounds和class
            verified_bounds = None
            verified_class = None
            verified_text = None
            verified_resource_id = None
            verified_content_description = None
            
            
            if 'event' in event and 'view' in event['event']:
                view = event['event']['view']
                if 'bounds' in view:
                    verified_bounds = view['bounds']
                if 'class' in view:
                    verified_class = view['class']
                if 'text' in view:
                    verified_text = view['text']
                if 'resource_id' in view:
                    verified_resource_id = view['resource_id']
                if 'content_description' in view:
                    verified_content_description = view['content_description']
            
                
            # 将bounds转换为字符串格式 [x1,y1][x2,y2]
            verified_bounds_str = f"[{verified_bounds[0][0]},{verified_bounds[0][1]}][{verified_bounds[1][0]},{verified_bounds[1][1]}]"
            
        except Exception as e:
            print(f"Error reading event file: {e}")
            return None
        
        # 2. 在XML树中查找具有相同属性的结点
        if xml_tree is None:
            print("XML tree is None")
            return None
            
        root = xml_tree.getroot()

        for node in root.iter():
            attrs = node.attrib

            def norm(v):
                # 把 None 或 "" 都归一到 None
                return v if v not in (None, "") else None

            current_bounds = norm(attrs.get('bounds'))
            current_class = norm(attrs.get('class'))
            current_text = norm(attrs.get('text'))
            current_resource_id = norm(attrs.get('resource-id'))
            current_content_desc = norm(attrs.get('content-desc'))

            match = True

            if verified_bounds_str is not None and current_bounds != verified_bounds_str:
                match = False
            if verified_class is not None and current_class != verified_class:
                match = False
            if verified_text is not None and current_text != verified_text:
                match = False
            if verified_resource_id is not None and current_resource_id != verified_resource_id:
                match = False
            if verified_content_description is not None and current_content_desc != verified_content_description:
                match = False

            if match:
                return node

        
        # 返回找到的元素对象
        return None

    

    def _is_view_excluded(self, view):
        """
        检查一个 view 是否在排除列表中

        Args:
            view: 要检查的 view 字典

        Returns:
            True 如果被排除，False 否则
        """
        if not self.excluded_views:
            return False

        view_str = view.get('view_str', '')
        view_bounds = view.get('bounds', [])

        for excluded in self.excluded_views:
            # 用 view_str 比较（唯一标识）
            if excluded.get('view_str') == view_str:
                return True
            # 或者用 bounds 比较
            if excluded.get('bounds') == view_bounds:
                return True

        return False

    def _get_view_navigation_id(self, view, activity=None, click_type=None):
        """
        生成 view 的导航唯一标识，用于判断是否已经访问过

        Args:
            view: view 字典
            activity: 当前 activity 名称

        Returns:
            (activity, resource_id, class, content_desc) 元组
        """
        resource_id = view.get('resource_id', '') or ''
        class_name = view.get('class', '') or ''
        content_desc = view.get('content_description', '') or ''
        activity = activity or ''
        click_type = click_type or ''
        return (activity, resource_id, class_name, content_desc, click_type)


    def _filter_events_by_rules(self, events):
        """
        过滤重叠的事件，当多个事件的中心点被同一个 clickable 元素覆盖时，
        只保留最上层（drawing order 最大）的那个事件

        算法逻辑（参考 _HindenWidgetFilter）：
        1. 按 drawing order 从小到大遍历事件
        2. 使用 rtree 索引记录每个事件的中心点
        3. 当遇到一个 clickable 事件时，检查其 bounds 内是否包含之前事件的中心点
        4. 如果包含，则标记之前的事件为 covered（被遮挡）
        5. 最后只返回未被遮挡的事件

        Args:
            events: 原始事件列表

        Returns:
            filtered_events: 过滤后的事件列表
        """
        import rtree

        self.logger.info(f"Filtering events: original count = {len(events)}")

        # 如果事件列表为空，直接返回
        if not events:
            return events

        try:
            # 按 drawing order 排序事件
            def get_drawing_order(event):
                if hasattr(event, 'view') and event.view:
                    return event.view.get('drawing-order', 0) or 0
                return 0

            sorted_events = sorted(events, key=get_drawing_order)

            # 使用 rtree 索引
            idx = rtree.index.Index()
            event_nodes = []  # 保存事件和其 covered 状态
            covered_set = set()  # 被遮挡的事件索引

            for event in sorted_events:
                # 非 view 事件直接添加
                if not hasattr(event, 'view') or not event.view:
                    event_nodes.append(event)
                    continue

                bounds = event.view.get('bounds')
                if not bounds:
                    event_nodes.append(event)
                    continue

                # 解析 bounds: [[x1, y1], [x2, y2]]
                x1, y1 = bounds[0]
                x2, y2 = bounds[1]

                # 检查当前事件是否是 clickable
                clickable = event.view.get('clickable', False)

                if clickable:
                    # 查找被当前事件覆盖的之前事件（中心点在当前 bounds 内）
                    covered_ids = list(idx.intersection((x1, y1, x2, y2)))
                    for covered_id in covered_ids:
                        # 检查被覆盖的事件是否来自同一个 view（相同 bounds）
                        # 如果是同一个 view 的不同事件类型，不应该被过滤
                        covered_event = event_nodes[covered_id]
                        if hasattr(covered_event, 'view') and covered_event.view:
                            cb = covered_event.view.get('bounds')
                            if cb:
                                # 如果 bounds 相同，说明是同一个 view，跳过
                                if cb == bounds:
                                    continue
                                # 不同 view，标记为 covered
                                covered_set.add(covered_id)
                                # 从索引中删除被覆盖的事件
                                cx = (cb[0][0] + cb[1][0]) / 2
                                cy = (cb[0][1] + cb[1][1]) / 2
                                idx.delete(covered_id, (cx, cy, cx, cy))

                # 计算当前事件的中心点并插入索引
                center_x = (x1 + x2) / 2
                center_y = (y1 + y2) / 2
                cur_id = len(event_nodes)
                idx.insert(cur_id, (center_x, center_y, center_x, center_y))
                event_nodes.append(event)

            # 过滤掉被遮挡的事件
            filtered_events = []
            for i, event in enumerate(event_nodes):
                if i not in covered_set:
                    filtered_events.append(event)

            self.logger.info(f"Filter stats: covered={len(covered_set)}, kept={len(filtered_events)}")
            self.logger.info(f"Events after filtering: {len(filtered_events)}")
            return filtered_events

        except Exception as e:
            self.logger.error(f"Error in _filter_events_by_uimatch_rules: {e}")
            import traceback
            traceback.print_exc()
            # 出错时返回原始事件列表
            return events

    def _find_element_by_bounds(self, xml_tree, bounds_str):
        """
        在XML树中查找具有指定bounds的元素
        
        Args:
            xml_tree: XML树
            bounds_str: bounds字符串，格式为[x1,y1][x2,y2]
            
        Returns:
            找到的元素或None
        """
        for element in xml_tree.iter():
            if element.get("bounds") == bounds_str:
                return element
        return None

    
    def _parse_bounds(self, bounds_str):
        """
        解析bounds字符串为坐标列表

        Args:
            bounds_str: "[x1,y1][x2,y2]" 格式的字符串

        Returns:
            [[x1, y1], [x2, y2]] 格式的列表
        """
        import re
        match = re.findall(r'\[(\d+),(\d+)\]', bounds_str)
        if len(match) == 2:
            return [[int(match[0][0]), int(match[0][1])],
                    [int(match[1][0]), int(match[1][1])]]
        return [[0, 0], [0, 0]]

    def save_repair_trace(self):
        """
        保存完整的修复轨迹到文件
        """
        try:
            repair_log_dir = os.path.join(self.exploration_tmp_dir, "repair_logs")
            os.makedirs(repair_log_dir, exist_ok=True)

            repair_log_path = os.path.join(
                repair_log_dir,
                f"repair_trace_event_{self.failed_event_number}.json"
            )

            # 判断是否修复成功（最后一步的 found_target 为 True）
            repair_success = False
            if self.repair_trace and self.repair_trace[-1].get('found_target'):
                repair_success = True

            # 完整的修复轨迹
            repair_log = {
                'failed_event_number': self.failed_event_number,
                'repair_success': repair_success,
                'total_steps': len(self.repair_trace),
                'timestamp': str(__import__('datetime').datetime.now()),
                'trace': self.repair_trace  # 保存完整的 trace 列表
            }

            # 保存到JSON文件
            with open(repair_log_path, 'w', encoding='utf-8') as f:
                json.dump(repair_log, f, indent=2, ensure_ascii=False)

            self.logger.info(f"✓ Repair trace saved to: {repair_log_path}")

        except Exception as e:
            self.logger.error(f"Error saving repair trace: {e}")
            import traceback
            traceback.print_exc()

    def check_if_same(self, current, record):
        if current is None or record is None:
            return False
        if current == record:
            return True
        return False

    def replace_view(self, event, current_view):
        event.view['resource_id'] = current_view['resource_id']
        event.view['text'] = current_view['text']
        event.view['content_description'] = current_view['content_description']
        event.view['class'] = current_view['class']
        event.view['instance'] = current_view['instance']
        event.view['bounds'] = current_view['bounds']

    def check_which_exists(self, event):
        resource_id = MatchingPolicy.__safe_dict_get(event.view, 'resource_id')
        text = MatchingPolicy.__safe_dict_get(event.view, 'text')
        content_description = MatchingPolicy.__safe_dict_get(event.view, 'content_description')
        class_name = MatchingPolicy.__safe_dict_get(event.view, 'class')
        instance = MatchingPolicy.__safe_dict_get(event.view, 'instance')

        u2 = self.device.u2
        

        if content_description is not None:
            if u2.exists(description=content_description, instance=instance):
                for current_view in self.current_state.views:
                    if self.check_if_same(current_view['content_description'], content_description) and self.check_if_same(current_view['instance'], instance):
                        self.replace_view(event, current_view)
                        break
                return 'content_description', content_description
        elif text is not None:
            if u2.exists(text=text, instance=instance):
                for current_view in self.current_state.views:
                    if self.check_if_same(current_view['text'], text) and self.check_if_same(current_view['instance'], instance):
                        self.replace_view(event, current_view)
                        break
                return 'text', text
        elif resource_id is not None:
            if u2.exists(resourceId=resource_id, instance=instance):
                for current_view in self.current_state.views:
                    if self.check_if_same(current_view['resource_id'], resource_id) and self.check_if_same(current_view['instance'], instance):
                        self.replace_view(event, current_view)
                        break
                return 'resource_id', resource_id
        elif class_name is not None:
            if u2.exists(className=class_name, instance=instance):
                for current_view in self.current_state.views:
                    if self.check_if_same(current_view['class'], class_name) and self.check_if_same(current_view['instance'], instance):
                        self.replace_view(event, current_view)
                        break
                return 'class_name', class_name
        elif class_name is not None and resource_id is not None and instance is not None:
            if u2.exists(className=class_name, resourceId=resource_id, instance=instance):
                for current_view in self.current_state.views:
                    if self.check_if_same(current_view['class'], class_name) and self.check_if_same(current_view['resource_id'], resource_id) and self.check_if_same(current_view['instance'], instance):
                        self.replace_view(event, current_view)
                        break
                return 'class_resource_instance', (class_name, resource_id, instance)
        
        return None, None
    

    @staticmethod
    def __safe_dict_get(view_dict, key, default=None):
        value = view_dict[key] if key in view_dict else None
        return value if value is not None else default