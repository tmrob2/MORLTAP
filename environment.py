from grid import Grid, GOAL_VALUE, WALL_VALUE
import numpy as np
from typing import List, Tuple, Optional, Dict
from utils import Coord
from abc import abstractmethod
import copy


VISIBLE_RADIUS = 1


class EnvHistory:
    def __init__(self, position, grid, energy, visible, success):
        self.position = position
        self.grid = grid
        self.energy = energy
        self.visibles = visible
        self.success = success


class State:
    def __init__(self, energy, position: Coord):
        self.energy = energy
        self.position = position

    def to_ndarray(self):
        return np.array([self.energy, self.position.x, self.position.y])

    def __str__(self):
        return "pos: ({},{}), e: {}".format(self.position.x, self.position.y, self.energy)


class Environment:

    ENERGY = None
    STEP_VALUE = -0.02

    def __init__(self, grid_size, n_objs, start_energy, start_location: Coord, num_tasks, step_value=None, name=None):
        self.grid = Grid(grid_size=grid_size, n_obj=n_objs)
        self.t = 0
        self.history = []
        self.position = Coord()
        self.start_position = Coord()
        self.position.set(start_location.x, start_location.y)
        self.start_position = copy.copy(self.position)
        self.energy = start_energy
        self.ENERGY = start_energy
        self.num_tasks = num_tasks
        self.dead = False
        self.success = False
        self.visible = None
        self.name = name
        if step_value is not None:
            self.STEP_VALUE = step_value


    @abstractmethod
    def act(self, action):
        ...

    def set_init_state(self, position: Coord, energy):
        self.position = position
        self.energy = energy
        self.start_position = self.position

    def reset(self):
        """Start a new episode by resetting the grid and a agents"""
        self.grid.reset()
        self.position = copy.copy(self.start_position)
        self.t = 0
        self.history = []
        self.energy = self.ENERGY
        self.dead = False
        self.success = False
        self.visible = None
        return self._visible_state

    @property
    def _visible_state(self):
        """State of the system"""
        state = State(energy=self.energy, position=self.position).to_ndarray()
        return state

    def _set_visibility(self, grid):
        self.visible = np.array(grid.visible(self.position))

    def _record_step(self):
        """Add the current state to history for display later"""
        grid = np.array(self.grid.grid)
        grid[self.position.x, self.position.y] = self.energy * 0.5
        self._set_visibility(self.grid)
        self.history.append(EnvHistory(self.position, grid, self.energy, self.visible, self.success))

    def step(self, action):
        """Because this is a MAS we need to update the state of the system based on all of the agents"""
        rewards = np.array([0] * (self.num_tasks + 1))  # will be size j

        # Todo at this point we also have to generate a word, or each agent must generate a
        #  word but we will leave this for now and work on the agents moving around
        if not(self.dead or self.success):
            #print("success: {}, dead: {}".format(self.success, self.dead))
            self.act(action)
            value = self.grid.grid[self.position.x, self.position.y]
            self.energy += value
            if self.energy <= 0.0:
                self.dead = True
            #print("e < 0", self.energy <= 0.0)
            # the task rewards needs to be implemented via a Task
            if value == WALL_VALUE:
                rewards[0] = self.energy
                rewards[1] = 1.0
                self.success = True
        done = True if self.success or self.dead else False
        self._record_step()
        return self._visible_state, rewards, done



