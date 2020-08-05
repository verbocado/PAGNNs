import numpy as np
import numba
from numba import jit, float64 
import time

@jit(float64[:, :](float64[:, :], float64[:, :]), nopython=True)
def _step(graph_weights, latent_graph_state):
    next_state = np.zeros(latent_graph_state.shape)

    for i in range(latent_graph_state.shape[0]):
        # next_state += self.graph_weights * np.transpose([neuron]) # this method is MUCH slower
        next_state += graph_weights.T * latent_graph_state[i] 

    return next_state.T

class GraphFFNN:

    def __init__(self, input_dim, hidden_units, output_dim, use_bias=True):
        self.input_dim = input_dim
        self.output_dim = output_dim
        self.hidden_units = hidden_units

        # Define the weights and biases in the normal neural network domain.
        self.W = []
        self.B = []
        prev_units = input_dim
        self._num_neurons = input_dim
        for units in list(hidden_units) + [output_dim]:
            self._num_neurons += units
            max_magnitude = np.sqrt(prev_units * units)
            
            self.W.append(np.random.uniform(low=-max_magnitude, high=max_magnitude, size=(prev_units, units)))
            
            if use_bias:
                self.B.append(np.random.uniform(low=-max_magnitude, high=max_magnitude, size=(units, )))
            else:
                self.B.append(np.zeros(shape=(units,)))

            prev_units = units

        # Define the weights in the graph-based neural network domain.
        
        # Input data is also considered to be made up of neurons. To understand this better, I would like to bring in an analogy to the human nervous system. Our 
        # nervous system is made up of trillions of neurons. What exactly a neuron is is a transmitter of electrical signals. You can think of the nervous system
        # as an extension of our brains, tendrils running out to gather data about our immediate environment. Therefore, our brain takes in inputs through  neurons
        # whether that be directly or indirectly through our environmental sensors.

        # Traditional thinking in the ANN research community is to conceptually separate these environmental sensors. However, if Monism has taught us anything,
        # it's that we are one with our environment, one with ourself, and one with the universe. So why should our networks be treated any differently?

        # Weights in this representation should be thought of as the synapses in our brains. Though this class is specific to feed forward neural networks, the
        # same structure should generally apply to any architecture of neurons and synapses.

        # Another point I'd like to make, is that in this representation the network has a state. This state is a representation of the latent variables at a given
        # time step. In a feed forward neural network, the forward pass' number of states are relative to the number of layers there are in the network. For example,
        # a network with 6 layers will have 7 states in the forward pass. 1=input loading, 2=layer1 pass, 3=layer2 pass, ..., 7=layer5 pass. After it propagates
        # through each state (assuming there are no occilations in the architecture, like a feed forward neural network), the "output" will be stored in the graph
        # nodes representing the output dimensions. This is kept as a batch size of 1 to understand conceptually.

        self.graph_weights = np.zeros((self._num_neurons, self._num_neurons)) # Matrix graph representation for our weights
        
        # initialize graph_weights with the same weights as the normal mode
        neuron_idx = 0
        for W, B in zip(self.W, self.B):
            N, D = W.shape
            self.graph_weights[neuron_idx:neuron_idx+N, neuron_idx+N:neuron_idx+D+N] = W
            neuron_idx += N

        # set last neurons to be connected to themselves (for now) TODO: change this, doesn't make sense for general application
        for i in range(output_dim):
            self.graph_weights[-(i+1), -(i+1)] = 1

    def normal_forward(self, X):
        Z = X.T
        for W, B in zip(self.W, self.B):
            Z = np.dot(W.T, Z)
            Z += np.transpose([B])
        Y = Z.T
        return Y

    def graph_forward(self, X):
        # TODO: handle batch later
        state = X[0]
        D = len(state)
        state = np.pad(state, (0, self._num_neurons-D))
        # state = self.graph_weights * np.transpose([state])
        state = (self.graph_weights.T * state).T

        for _ in range(len(self.hidden_units)+1):
            state = self.graph_step(state)
        
        # extract the output neurons after the steps
        Y = np.expand_dims(self.extract_output(state), axis=0)
        return Y


    def graph_step(self, latent_graph_state):
        # TODO: make more efficient, for now we're traversing the graph nodes to their next edges
        
        # next_state = np.zeros(latent_graph_state.shape)

        # for neuron in latent_graph_state:
            # next_state += self.graph_weights * np.transpose([neuron]) # this method is MUCH slower
            # next_state += self.graph_weights.T * neuron 
        # return next_state.T
        return _step(self.graph_weights, latent_graph_state)

    def extract_output(self, latent_graph_state):
        Y = np.zeros(self.output_dim)
        c = 0
        for i in range(self.output_dim, 0, -1):
            Y[c] = latent_graph_state[-i, -i]
            c += 1
        return Y 

    def __str__(self):
        return str(self._num_neurons)


if __name__ == '__main__':
    input_features = 3
    output_features = 2

    gnn = GraphFFNN(input_features, (3, 5, 5, 3), output_features, use_bias=False)
    print('Number of neurons:', gnn._num_neurons)
    
    # create input data
    X = np.random.randint(1000, size=(1, input_features))
    print('X:', X)
    print()
    
    # test normal neural network domain inference
    start = time.time()
    y = gnn.normal_forward(X)
    normal_dt = time.time() - start
    print('Normal output:')
    print(y)

    # since we're using numba, give it some time to warm up before comparing times
    gnn.graph_forward(X)
    gnn.graph_forward(X)

    start = time.time()
    y_graph = gnn.graph_forward(X)
    graph_dt = time.time() - start
    print('Graph output:')
    print(y_graph)

    print()
    print('Time Deltas:')
    print('Normal: %fms' % (normal_dt*1000))
    print('Graph: %fms' % (graph_dt*1000))
    print('Graph is %.3fx slower.' % (graph_dt / normal_dt))

    # print()
    # print(gnn.graph_weights)
    # print()