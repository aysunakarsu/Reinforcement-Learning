import numpy as np
import random
from collections import namedtuple, deque

from model import QNetwork

import torch
import torch.nn.functional as F
import torch.optim as optim

BUFFER_SIZE = int(1e5)  # replay buffer size
BATCH_SIZE = 32         # minibatch size
GAMMA = 0.99            # discount factor
TAU = 1e-3              # for soft update of target parameters
LR = 5e-4               # learning rate 
UPDATE_EVERY = 4        # how often to update the network

device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")

class Agent():
    """Interacts with and learns from the environment."""

    def __init__(self, action_size, frame_history=4, seed=42):
        """Initialize an Agent object.
        
        Params
        ======
            action_size (int): Dimension of each action
            frame_history (int): Number of continuous frames to be considered in each state 
            seed (int): Random seed
        """
        self.action_size = action_size
        self.seed = random.seed(seed)

        # Q-Network
        self.qnetwork_local = QNetwork(action_size, frame_history, seed).to(device)
        self.qnetwork_target = QNetwork(action_size, frame_history, seed).to(device)
        self.optimizer = optim.Adam(self.qnetwork_local.parameters(), lr=LR)

        # Replay memory
        self.memory = ReplayBuffer(action_size, BUFFER_SIZE, BATCH_SIZE, frame_history, seed)
        # Initialize time step (for updating every UPDATE_EVERY steps)
        self.t_step = 0
    
    def step(self, state, action, reward, next_state, done):
        # Save experience in replay memory
        self.memory.add(state, action, reward, next_state, done)
        
        # Learn every UPDATE_EVERY time steps.
        self.t_step = (self.t_step + 1) % UPDATE_EVERY
        if self.t_step == 0:
            # If enough samples are available in memory, get random subset and learn
            if len(self.memory) > BATCH_SIZE:
                experiences = self.memory.sample()
                self.learn(experiences, GAMMA)

    def act(self, state, eps=0.):
        """Returns actions for given state as per current policy.
        
        Params
        ======
            state (array_like): current state
            eps (float): epsilon, for epsilon-greedy action selection
        """

        # Epsilon-greedy action selection
        if random.random() > eps:
            state = torch.from_numpy(state).float().unsqueeze(0).to(device)
            
            self.qnetwork_local.eval()
            with torch.no_grad():
                action_values = self.qnetwork_local(state)
            self.qnetwork_local.train()
            
            return np.argmax(action_values.cpu().data.numpy())
        else:
            return random.choice(np.arange(self.action_size))

    def learn(self, experiences, gamma):
        """Update value parameters using given batch of experience tuples.

        Params
        ======
            experiences (Tuple[torch.Variable]): tuple of (s, a, r, s', done) tuples 
            gamma (float): discount factor
        """
        states, actions, rewards, next_states, dones = experiences
        
        ################
        # Double DQN   #
        ################
        # Get predicted Q values (for next states) from target model
        # corresponding to the max Q value action predicted by the local model
        next_state_actions = self.qnetwork_local(next_states).detach().max(1, keepdim=True)[1]
        Q_targets_next = self.qnetwork_target(next_states).detach().gather(1, next_state_actions)
        
        # Compute Q targets for current states 
        Q_targets = rewards + (gamma * Q_targets_next * (1 - dones))

        # Get expected Q values from local model
        Q_expected = self.qnetwork_local(states).gather(1, actions)

        # Compute loss
        loss = F.smooth_l1_loss(Q_expected, Q_targets)
        
        # Minimize the loss
        self.optimizer.zero_grad()
        loss.backward()
        self.optimizer.step()

        # ------------------- update target network ------------------- #
        self.soft_update(self.qnetwork_local, self.qnetwork_target, TAU)                     

    def soft_update(self, local_model, target_model, tau):
        """Soft update model parameters.
        θ_target = τ*θ_local + (1 - τ)*θ_target

        Params
        ======
            local_model (PyTorch model): weights will be copied from
            target_model (PyTorch model): weights will be copied to
            tau (float): interpolation parameter 
        """
        for target_param, local_param in zip(target_model.parameters(), local_model.parameters()):
            target_param.data.copy_(tau*local_param.data + (1.0-tau)*target_param.data)


class ReplayBuffer:
    """Fixed-size buffer to store experience tuples."""

    def __init__(self, action_size, buffer_size, batch_size, frame_history, seed):
        """Initialize a ReplayBuffer object.

        Params
        ======
            action_size (int): dimension of each action
            buffer_size (int): maximum size of buffer
            batch_size (int): size of each training batch
            frame_history (int): number of continuous frames to be considered in each state 
            seed (int): random seed
        """
        self.action_size = action_size
        self.buffer_size = buffer_size
        self.memory = deque(maxlen=buffer_size)  
        self.batch_size = batch_size
        self.frame_history = frame_history
        self.experience = namedtuple("Experience", field_names=["state", "action", "reward", "next_state", "done"])
        self.seed = random.seed(seed)
    
    def add(self, state, action, reward, next_state, done):
        """Add a new experience to memory."""
        e = self.experience(state, action, reward, next_state, done)
        self.memory.append(e)
    
    def _encode_state(self, idx):
        """Helper function to append context history to a state specified by idx in memory"""
        end_idx   = idx + 1 # make noninclusive
        start_idx = end_idx - self.frame_history
        n = len(self.memory)
        # if there weren't enough frames ever in the buffer for context
        if start_idx < 0:
            start_idx = 0
        for idx in range(start_idx, end_idx - 1):
            if self.memory[idx % n].done:
                start_idx = idx + 1
        missing_context = self.frame_history - (end_idx - start_idx)
        # if zero padding is needed for missing context
        # or we are on the boundry of the buffer
        frames = []
        if start_idx < 0 or missing_context > 0:
            frames = [np.zeros_like(self.memory[0].state) for _ in range(missing_context)]
            for idx in range(start_idx, end_idx):
                frames.append(self.memory[idx % n].state)
        else:
            for idx in range(start_idx, end_idx):
                frames.append(self.memory[idx % n].state)
                
        return np.expand_dims(np.array(np.concatenate(frames, 0) / 255.0, dtype=np.float32), axis=0) # normalize by 255
        
    def get_experiences(self, experiences_idx):
        """Create experiences where states have a context history in them"""
        experiences = []
        for idx in experiences_idx:
            state = self._encode_state(idx)
            next_state = self._encode_state(idx+1)
            e = self.experience(state, self.memory[idx].action, self.memory[idx].reward, next_state, self.memory[idx].done)
            experiences.append(e)
            
        return experiences
    
    def sample(self):
        """Randomly sample a batch of experiences from memory."""
        experiences_idx = random.sample(range(len(self.memory)), k=self.batch_size)
        experiences = self.get_experiences(experiences_idx)

        states = torch.from_numpy(np.vstack([e.state for e in experiences if e is not None])).float().to(device)
        actions = torch.from_numpy(np.vstack([e.action for e in experiences if e is not None])).long().to(device)
        rewards = torch.from_numpy(np.vstack([e.reward for e in experiences if e is not None])).float().to(device)
        next_states = torch.from_numpy(np.vstack([e.next_state for e in experiences if e is not None])).float().to(device)
        dones = torch.from_numpy(np.vstack([e.done for e in experiences if e is not None]).astype(np.uint8)).float().to(device)
  
        return (states, actions, rewards, next_states, dones)

    def __len__(self):
        """Return the current size of internal memory."""
        return len(self.memory)