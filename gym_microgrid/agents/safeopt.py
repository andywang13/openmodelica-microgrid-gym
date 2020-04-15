import importlib
from typing import Dict, Union, Any

import GPy
from GPy.kern import Kern
from safeopt import SafeOptSwarm

from gym_microgrid.agents.staticctrl import StaticControlAgent
from gym_microgrid.agents.util import MutableParams
from gym_microgrid.auxiliaries import Controller
from gym_microgrid.env import EmptyHistory

import matplotlib.pyplot as plt

import numpy as np


class SafeOptAgent(StaticControlAgent):
    def __init__(self, mutable_params: Union[dict, list], kernel: Kern, gp_params: Dict[str, Any],
                 ctrls: Dict[str, Controller],
                 observation_action_mapping: dict, history=EmptyHistory()):
        self.params = MutableParams(
            list(mutable_params.values()) if isinstance(mutable_params, dict) else mutable_params)
        self.kernel = kernel
        self.bounds = gp_params['bounds']
        self.noise_var = gp_params['noise_var']

        self.episode_reward = None
        self.optimizer = None
        self.inital_Performance = None
        self._iterations = 0
        super().__init__(ctrls, observation_action_mapping, history)
        self.history.cols = ['J', 'Params']

    def reset(self):
        # reinstantiate kernel

        kernel_params = self.kernel.to_dict()
        cls_name = kernel_params['class']
        mod = importlib.import_module('.'.join(cls_name.split('.')[:-1]))
        cls = getattr(mod, cls_name.split('.')[-1])
        remaining_params = {k: v for k, v in kernel_params.items() if k not in {'class', 'useGPU'}}
        self.kernel = cls(**remaining_params)

        self.params.reset()
        self.optimizer = None
        self.episode_reward = 0
        self.inital_Performance = None
        self._iterations = 0
        return super().reset()

    def observe(self, reward, terminated):
        self._iterations += 1
        self.episode_reward += reward or 0
        if terminated:
            # calculate MSE, divide Summed error by length of measurement
            self.episode_reward = self.episode_reward / self._iterations
            # safeopt update step
            self.update_params()
            # reset for new episode
            self.prepare_episode()
        # on other steps we don't need to do anything

    def update_params(self):
        if self.optimizer is None:
            # First Iteration
            # self.inital_Performance = 1 / self.episode_reward
            self.inital_Performance = self.episode_reward
            # Norm for Safe-point
            # J = 1 / self.episode_reward / self.inital_Performance

            J = self.inital_Performance


            # Define Mean "Offset": Like BK: Assume Mean = Threshold (BK = 0, now = 20% below first (safe) J: means: if
            # new Performance is 20 % lower than the inital we assume as unsafe)
            mf = GPy.core.Mapping(len(self.bounds), 1)
            mf.f = lambda x: 1.2 * J
            mf.update_gradients = lambda a, b: 0
            mf.gradients_X = lambda a, b: 0

            gp = GPy.models.GPRegression(np.array([self.params[:]]),
                                         np.array([[J]]), self.kernel,
                                         noise_var=self.noise_var, mean_function=mf)
            self.optimizer = SafeOptSwarm(gp, 1.2 * J, bounds=self.bounds, threshold=1)
            """
            # Mean Free GP - 
            # ToDo: Still needed?
            gp = GPy.models.GPRegression(np.array([self.params[:]]),
                                         np.array([[J]]), self.kernel,
                                         noise_var=noise_var)
            self.optimizer = SafeOptSwarm(gp, 0, bounds=bounds, threshold=1)
            """
        else:

            if np.isnan(self.episode_reward):
                # set r to doubled (negative!) initial reward
                self.episode_reward = 2 * self.inital_Performance

            J = self.episode_reward

            self.optimizer.add_new_data_point(self.params[:], J)

        self.history.append([J, self.params[:]])
        self.params[:] = self.optimizer.optimize()

    def render(self):
        plt.figure()
        self.optimizer.plot(1000)
        plt.show()
