import gym
import numpy as np
import torch
import random
import torch.nn.functional as F
from pagnn.pagnn import PAGNNLayer
from copy import deepcopy


device = torch.device('cuda') if torch.cuda.is_available() else torch.device('cpu')


def play_episodes(env, network, episodes=5, max_steps=200, render=False, verbose=False):
    env.reset()
    env.seed(np.random.randint(999999999)) # seed according to numpy so we can reproduce results every time
    scores = []

    for i_episode in range(episodes):
        observation = env.reset()
        network.reset_state(network._total_neurons)
        score = 0

        for t in range(max_steps):
            if render:
                env.render()

            x = torch.tensor(observation, device=device)
            y = network(x)
            action = torch.argmax(y).item()
            
            observation, reward, done, info = env.step(action)
            score += reward
            if done:
                if verbose:
                    print("Episode finished after {} timesteps, score: {}".format(t+1, score))

                break

        scores.append(score)

    if render:
        env.close()

    return scores


def genome_generator(input_size, output_size, extra_neurons, retain_state):
    return PAGNNLayer(input_size, output_size, extra_neurons, retain_state=retain_state).to(device)


def get_random_genomes(n, input_size, output_size, extra_neurons, retain_state):
    return [genome_generator(input_size, output_size, extra_neurons, retain_state) for _ in range(n)]


@torch.no_grad()
def mutate(genome, w_prob=1e-4, p_prob=1e-2, max_magnitude=0.5):
    w = genome.weight
    b = genome.bias

    w_mutate_mask = torch.rand(w.shape, device=device) < w_prob
    b_mutate_mask = torch.rand(b.shape, device=device) < p_prob
    w += w_mutate_mask * ((torch.rand(w.shape, device=device) - 0.5) * (max_magnitude * 2))
    b += b_mutate_mask * ((torch.rand(b.shape, device=device) - 0.5) * (max_magnitude * 2))

    return genome


@torch.no_grad()
def crossover(genome1, genome2):
    w1 = genome1.weight
    b1 = genome1.bias
    w2 = genome2.weight
    b2 = genome2.bias

    w1_flat = w1.view(-1)
    w_numel = w1.numel()
    b_numel = b1.numel()

    # get masks
    w_share = int(np.random.uniform(0, 1) * w_numel)
    b_share = int(np.random.uniform(0, 1) * b_numel)
    w_mask = torch.where(torch.arange(w_numel) < w_share, torch.ones(w_numel), torch.zeros(w_numel)).view(w1.shape).to(device)
    b_mask = torch.where(torch.arange(b_numel) < b_share, torch.ones(b_numel), torch.zeros(b_numel)).view(b1.shape).to(device)
    
    # get weights/biases from parents according to masks
    cw = torch.zeros_like(w1)
    cw += w1 * w_mask
    cw += w2 * (w_mask == 0)
    cb = torch.zeros_like(b1)
    cb += b1 * b_mask
    cb += b2 * (b_mask == 0)

    child = genome_generator(input_size=genome1._input_neurons, output_size=genome1._output_neurons, extra_neurons=genome1._extra_neurons, retain_state=genome1._retain_state)
    child.weight.data = cw
    child.bias.data = cb

    return mutate(child)


def get_next_population(current_genomes, scores, n, search_type, input_size, output_size, extra_neurons, retain_state):
    if search_type == 'random':
        genomes = get_random_genomes(n, input_size=input_size, output_size=output_size, extra_neurons=extra_neurons, retain_state=retain_state)

    elif search_type == 'evolutionary':
        # normalize scores
        scores = scores / torch.linalg.norm(scores)

        # turn scores into probability distribution
        scores = F.softmax(scores, dim=0).numpy()

        n_random = int(0.1 * n)

        # select parents
        indices = np.arange(n)
        parent_pairs = np.random.choice(indices, (n-1-n_random, 2), p=scores)

        # keep best
        best_idx = np.argmax(scores)
        genomes = [current_genomes[best_idx]]

        # do crossovers
        for i, (idx1, idx2) in enumerate(parent_pairs):
            parent1 = current_genomes[idx1]
            parent2 = current_genomes[idx2]
            child = crossover(parent1, parent2)
            genomes.append(child)

        # randomly initialize 10% of the new population
        for _ in range(n_random):
            genomes.append(genome_generator(input_size, output_size, extra_neurons, retain_state))
    
        assert len(genomes) == len(current_genomes)

    else:
        raise Exception()

    return genomes


def get_space_len(space):
    if hasattr(space, 'n'):
        return space.n
    if hasattr(space, 'shape'):
        return np.prod(space.shape)
    raise Exception()


def deterministic():
    np.random.seed(666)
    torch.manual_seed(666)
    torch.backends.cudnn.deterministic = True
    torch.backends.cudnn.benchmark = False
    random.seed(666)


def run(env_string, generations=10, population_size=100, best_replay=False, search_type='random', extra_neurons=5, retain_state=False):
    env = gym.make(env_string)
    ins = get_space_len(env.observation_space)
    outs = get_space_len(env.action_space)

    # first generation is always random
    genomes = get_random_genomes(population_size, input_size=ins, output_size=outs, extra_neurons=extra_neurons, retain_state=retain_state) 

    best_genome = {'score': float('-inf')}

    for generation in range(generations):
        avg_scores_per_genome  = []

        # let genomes play
        for i, genome in enumerate(genomes):
            scores_per_episode = play_episodes(env, genome)
            avg_score = np.mean(scores_per_episode).item()
            avg_scores_per_genome.append(avg_score)

            if avg_score > best_genome['score']:
                best_genome = {'score': avg_score, 'state_dict': deepcopy(genome.state_dict())}

        print('generation %i best score:' % generation, best_genome['score'])

        # get next generation
        genomes = get_next_population(genomes, torch.tensor(avg_scores_per_genome), population_size, search_type, input_size=ins, output_size=outs, extra_neurons=extra_neurons, retain_state=retain_state)
    
    # replay
    if best_replay:
        genome = genome_generator(input_size=ins, output_size=outs, extra_neurons=extra_neurons, retain_state=retain_state)
        genome.load_state_dict(best_genome['state_dict'])
        play_episodes(env, genome, verbose=True, render=True, episodes=1, max_steps=5000)