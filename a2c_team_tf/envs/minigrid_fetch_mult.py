from gym_minigrid.minigrid import *

class MultObjNoGoal(MiniGridEnv):
    """
    Environment which has multiple objects present
    Suitable for multitask settings where rewards are generated through DFA
    """
    def __init__(
        self,
        size=8,
        numKeys=1,
        numBalls=1
    ):
        self.numKeys = numKeys
        self.numBalls = numBalls
        self.counts = {}

        super().__init__(
            grid_size=size,
            max_steps=5*size**2,
            # Set this to True for maximum speed
            see_through_walls=True
        )

    def _gen_grid(self, width, height):
        self.grid = Grid(width, height)

        # Generate the surrounding walls
        self.grid.horz_wall(0, 0)
        self.grid.horz_wall(0, height-1)
        self.grid.vert_wall(0, 0)
        self.grid.vert_wall(width-1, 0)

        types = ['key', 'ball']

        objs = []

        # For each object to be generated
        for key in range(self.numKeys):
            obj = Key('red')
            self.place_obj(obj)
            objs.append(obj)

        for ball in range(self.numBalls):
            obj = Ball('blue')
            self.place_obj(obj)
            objs.append(ball)

        # Randomize the player start position and orientation
        self.place_agent()

        # Choose a random object to be picked up
        # target = objs[self._rand_int(0, len(objs))]
        # self.targetType = target.type
        # self.targetColor = target.color

        self.mission = ""

    def step(self, action):
        self.step_count += 1

        reward = 0
        done = False

        # Get the position in front of the agent
        fwd_pos = self.front_pos

        # Get the contents of the cell in front of the agent
        fwd_cell = self.grid.get(*fwd_pos)

        # Rotate left
        if action == self.actions.left:
            self.agent_dir -= 1
            if self.agent_dir < 0:
                self.agent_dir += 4

        # Rotate right
        elif action == self.actions.right:
            self.agent_dir = (self.agent_dir + 1) % 4

        # Move forward
        elif action == self.actions.forward:
            if fwd_cell == None or fwd_cell.can_overlap():
                self.agent_pos = fwd_pos
            if fwd_cell != None and fwd_cell.type == 'lava':
                done = True

        # Pick up an object
        elif action == self.actions.pickup:
            if fwd_cell and fwd_cell.can_pickup():
                if self.carrying is None:
                    self.carrying = fwd_cell
                    self.carrying.cur_pos = np.array([-1, -1])
                    self.grid.set(*fwd_pos, None)

        # Drop an object
        elif action == self.actions.drop:
            if not fwd_cell and self.carrying:
                self.grid.set(*fwd_pos, self.carrying)
                self.carrying.cur_pos = fwd_pos
                self.carrying = None

        # Toggle/activate an object
        elif action == self.actions.toggle:
            if fwd_cell:
                fwd_cell.toggle(self, fwd_pos)

        # Done action (not used by default)
        elif action == self.actions.done:
            pass

        else:
            assert False, "unknown action"

        obs = self.gen_obs()

        return obs, reward, done, {}


class MultObjNoGoal5x5(MultObjNoGoal):
    def __init__(self):
        super().__init__(size=5, numKeys=1, numBalls=1)


class MultObjNoGoal4x4(MultObjNoGoal):
    def __init__(self):
        super().__init__(size=4, numKeys=1, numBalls=1)

class MultObj4x4ActBonus(MultObjNoGoal):
    def __init__(self):
        self.counts = {}
        super().__init__(size=4, numKeys=1, numBalls=1)

    def step(self, action):
        obs, reward, done, info = MultObjNoGoal.step(self, action)
        tup = (tuple(self.agent_pos), self.agent_dir, action)
        # Get the count for this (s, a) pair
        pre_count = 0
        if tup in self.counts:
            pre_count = self.counts[tup]

        # update the count for this state action pair
        new_count = pre_count + 1
        self.counts[tup] = new_count
        bonus = 1 / math.sqrt(new_count)
        reward += bonus
        return obs, reward, done, info