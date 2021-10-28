import numpy as np
import gym
import tensorflow as tf
from a2c_team_tf.utils.dfa import CrossProductDFA
from typing import List, Tuple

eps = np.finfo(np.float32).eps.item()
huber_loss = tf.keras.losses.Huber(reduction=tf.keras.losses.Reduction.SUM)


class TfObsEnv:
    def __init__(
            self,
            envs: List[gym.Env],
            models: List[tf.keras.Model],
            dfas: List[CrossProductDFA],
            m_tasks, n_agents, render=False, debug=False):
        self.envs: List[gym.Env] = envs
        self.dfas: List[CrossProductDFA] = dfas
        self.num_tasks = m_tasks
        self.num_agents = n_agents
        self.render: bool = render
        self.debug: bool = debug
        self.models: List[tf.keras.Model] = models
        self.mean: tf.Variable = tf.Variable(0.0, trainable=False)
        self.episode_reward: tf.Variable = tf.Variable(0.0, trainable=False)
        # here we set tau as a matrix of params, but it could be anything for example
        # params that a neural network could learn
        self.tau_params = tf.ones([n_agents, m_tasks], dtype=tf.float32)

    def env_step(self, action: np.ndarray, env_index: np.int32) \
            -> Tuple[List[np.ndarray], np.ndarray, np.ndarray]:
        """
        to be a tf graph, all inputs should be arrays
        :return state, reward and done. All outputs should be numpy arrays.
        """
        ii: int = env_index
        state, reward, done, _ = self.envs[ii].step(action)
        self.dfas[ii].next(self.envs[ii])  # sets the next state of the DFAs
        self.dfas[ii].non_reachable()
        rewards = [reward] + self.dfas[ii].rewards()

        if not self.dfas[ii].done():
            done = False
            rewards[0] = 0.0

        if self.dfas[ii].dead() or self.dfas[ii].done():
            done = True

        if self.debug:
            print("reward: {}".format(rewards))

        return state.astype(np.float32), np.array(rewards, np.float32), np.array(done, np.int32)

    def env_reset(self, env_index):
        state = self.envs[env_index].reset()
        self.dfas[env_index].reset()
        # print(f"dfa state: {self.dfas[env_index].product_state}")
        return state

    def tf_reset(self, env_index: tf.int32):
        return tf.numpy_function(self.env_reset, [env_index], [tf.float32])

    def tf_env_step(self, action: tf.Tensor, env_index: tf.int32) -> List[tf.Tensor]:
        """
        tensorflow function for wrapping the environment step function of the env object
        returns model parameters defined in shared.py of a tf.keras.model
        """
        return tf.numpy_function(self.env_step, [action, env_index], [tf.float32, tf.float32, tf.int32])

    @staticmethod
    def get_expected_returns(
            rewards: tf.Tensor,
            gamma: tf.float32,
            num_tasks: tf.int32,
            standardize: tf.bool = False) -> tf.Tensor:
        """Compute expected returns per timestep"""
        n = tf.shape(rewards)[0]
        returns = tf.TensorArray(dtype=tf.float32, size=n)

        # Start from the end of rewards and accumulate reward sums into the returns array
        rewards = tf.cast(rewards[::-1], dtype=tf.float32)

        # discounted_sum = tf.constant(0.0)
        discounted_sum = tf.constant([0.0] * (num_tasks + 1))
        discounted_sum_shape = discounted_sum.shape
        for i in tf.range(n):
            reward = rewards[i]
            discounted_sum = reward + gamma * discounted_sum
            discounted_sum.set_shape(discounted_sum_shape)
            returns = returns.write(i, discounted_sum)
        returns = returns.stack()[::-1]
        if standardize:
            returns = ((returns - tf.math.reduce_mean(returns)) /
                       (tf.math.reduce_std(returns) + eps))
        return returns

    @staticmethod
    def df(x: tf.Tensor, c: tf.float32) -> tf.Tensor:
      if tf.greater_equal(x, c):
          #tf.print(f"x: {x}, c: {c}")
          return 2*(x-c)
      else:
          return tf.convert_to_tensor(0.0)

    #@tf.function
    @staticmethod
    def dh(x: tf.float32, e: tf.float32) -> tf.Tensor:
        if tf.greater_equal(e, x) and tf.greater(x, 0.0):
            return tf.math.log(x / e) - tf.math.log((1.0 - x) / (1.0 - e))
        else:
            return tf.convert_to_tensor(0.0)

    #@tf.function
    def compute_H(self, X: tf.Tensor, Xi: tf.Tensor, agent: tf.int32, lam: tf.float32, chi: tf.float32, mu: tf.float32, e: tf.float32, c: tf.float32) -> tf.Tensor:
        """
        :param X: values (non-participant in gradient)
        :param Xi: initial_values (non-participant in gradient)
        :param lam: weigting assigned to the agent performance loss
        :param chi: weighting assigned to the task performance loss
        :param mu: probability of allocation, learned parameter
        :param e: task threshold [0,1]
        :return:
        """
        _, y = X.get_shape()
        # The size of H should be m_tasks + 1 (agent)
        # H_agent = tf.TensorArray(dtype=tf.float32, size=y)
        f = lam * self.df(Xi[0], c)
        # print(f"f: {f}")
        # this is the agent rewards, if the agent returns a value greater than c, then f > 0 otherwise f will be 0
        # optimal policies produce returns with either 0 or some minimised value of f.
        H_tasks = self.compute_task_H(X, agent, mu, chi, e)
        H = tf.concat([tf.expand_dims(f, 0), H_tasks], 0)
        # print(f"H: {H}")
        return H

    def compute_task_H(
            self,
            X: tf.Tensor,
            agent: tf.int32,
            mu: tf.Tensor,
            chi: tf.float32,
            e: tf.float32):
        H = tf.TensorArray(dtype=tf.float32, size=self.num_tasks)
        # todo check the dimensions of the h_val calculation as mu has been changed
        for j in tf.range(start=1, limit=self.num_tasks):
            h_val = chi * self.dh(tf.math.reduce_sum(mu[agent, j - 1] * X[:, j]), e) * mu[agent, j - 1]
            H = H.write(j, h_val)
        return H.stack()

    #@tf.function
    def compute_actor_loss(
            self,
            action_probs: tf.Tensor,
            values: tf.Tensor,
            returns: tf.Tensor,
            ini_value: tf.Tensor,
            ini_values_i: tf.Tensor,
            agent: tf.int32,
            lam: tf.float32,
            chi: tf.float32,
            mu: tf.Tensor,
            e: tf.float32,
            c: tf.float32) -> tf.Tensor:
        """Computes the combined actor-critic loss."""

        H = self.compute_H(ini_value, ini_values_i, agent, lam, chi, mu, e, c)
        H = tf.expand_dims(H, 0)
        advantage = tf.matmul(returns - values, tf.transpose(H))
        action_log_probs = tf.math.log(action_probs)
        actor_loss = tf.math.reduce_sum(action_log_probs * advantage)

        critic_loss = huber_loss(values, returns)

        # print(f'shape of action_log_probs:, {action_log_probs.get_shape()}')
        # print(f'shape of H:, {H.get_shape()}')
        # print(f'shape of advantage:, {advantage.get_shape()}')
        # print(f'shape of actor_loss:, {actor_loss.get_shape()}')
        # print(f'shape of critic_loss:, {critic_loss.get_shape()}')

        return actor_loss + critic_loss

    def compute_allocator_loss(
            self,
            X: tf.Tensor,
            agent: tf.int32,
            mu: tf.Tensor,
            chi: tf.float32,
            e: tf.float32,
            lr: tf.float32) -> tf.Tensor:
        H = self.compute_task_H(X, agent, mu, chi, e)
        #H = tf.expand_dims(H, 0)
        allocator_loss = lr * tf.math.reduce_sum(X[:, 1:] * H)
        print(f"X: {X[:, 1:]}, H: {H}")
        return allocator_loss

    def run_episode(
            self,
            initial_state: tf.Tensor,
            env_index: tf.int32,
            max_steps: tf.int32) -> Tuple[tf.Tensor, tf.Tensor, tf.Tensor]:
        """Runs a single episode to collect training data."""

        action_probs = tf.TensorArray(dtype=tf.float32, size=0, dynamic_size=True)
        values = tf.TensorArray(dtype=tf.float32, size=0, dynamic_size=True)
        rewards = tf.TensorArray(dtype=tf.float32, size=0, dynamic_size=True)
        initial_state_shape = initial_state.shape
        state = initial_state

        for t in tf.range(max_steps):
            # Convert state into a batched tensor (batch size = 1)
            state = tf.expand_dims(state, 0)

            # Run the model and to get action probabilities and critic value
            action_logits_t, value = self.models[env_index](state)

            # Sample next action from the action probability distribution
            action = tf.random.categorical(action_logits_t, 1)[0, 0]
            action_probs_t = tf.nn.softmax(action_logits_t)

            # Store critic values
            values = values.write(t, tf.squeeze(value))

            # Store log probability of the action chosen
            action_probs = action_probs.write(t, action_probs_t[0, action])

            # Apply action to the environment to get next state and reward
            state, reward, done = self.tf_env_step(action, env_index)
            reward = tf.squeeze(reward)
            state.set_shape(initial_state_shape)
            # print(f'state: {state}')

            # Store reward
            rewards = rewards.write(t, reward)

            if tf.cast(done, tf.bool):
                break

            if self.render:
                self.envs[env_index].render('human')

        action_probs = action_probs.stack()
        values = values.stack()
        rewards = rewards.stack()

        ## Reset the task score at the end of each episode.
        #task.reset()

        return action_probs, values, rewards

    #@tf.function
    def train_step(
            self,
            optimizer: tf.keras.optimizers.Optimizer,
            gamma: tf.float32,
            max_steps_per_episode: tf.int32,
            m_tasks: tf.int32,
            lam: tf.float32,
            chi: tf.float32,
            mu: tf.Tensor,
            e: tf.float32,
            c: tf.float32,
            alpha: tf.float32) -> tf.Tensor:

        num_models = len(self.models)
        action_probs_l = []
        values_l = []
        rewards_l = []
        returns_l = []
        actor_loss_l = []
        allocator_loss_l = []
        with tf.GradientTape() as tape:
            for i in range(num_models):
                initial_state = tf.constant(self.tf_reset(i), dtype=tf.float32)

                # Run an episode
                action_probs, values, rewards = self.run_episode(initial_state, i, max_steps_per_episode)
                #print(f"rewards: {rewards}")

                # Get expected rewards
                returns = self.get_expected_returns(rewards, gamma, m_tasks, False)

                # Append tensors to respective lists
                action_probs_l.append(action_probs)
                values_l.append(values)
                rewards_l.append(rewards)
                returns_l.append(returns)
            ini_values = tf.convert_to_tensor([x[0, :] for x in values_l])
            for i in range(num_models):
                # Get loss
                values = values_l[i]
                returns = returns_l[i]
                ini_values_i = ini_values[i]
                actor_loss = self.compute_actor_loss(action_probs_l[i], values, returns, ini_values, ini_values_i, i, lam, chi, mu, e, c)
                actor_loss_l.append(actor_loss)
                allocator_loss = self.compute_allocator_loss(ini_values, i, mu, chi, e, alpha)
                print(f"Shape allocator loss: {allocator_loss.shape}")
                allocator_loss_l.append(allocator_loss)

        print(f"Allocator loss: {len(allocator_loss_l)}")
        # compute the gradient from the loss vector
        xi_l = [m.trainable_variables for m in self.models]
        grads_xi_l = tape.gradient(actor_loss_l, xi_l)
        #grads_tau_l = tape.gradient(allocator_loss_l, self.tau_params)

        # Apply the gradients to the model's parameters
        grads_l_f = [x for y in grads_xi_l for x in y]
        vars_l_f = [x for y in xi_l for x in y]
        optimizer.apply_gradients(zip(grads_l_f, vars_l_f))
        episode_reward_l = [tf.math.reduce_sum(rewards_l[i]) for i in range(num_models)]
        #print(episode_reward_l)

        return episode_reward_l[0]



