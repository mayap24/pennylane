# Copyright 2018-2021 Xanadu Quantum Technologies Inc.

# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at

#     http://www.apache.org/licenses/LICENSE-2.0

# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""
This module contains functions for computing the vector-Jacobian product
of tapes.
"""
import numpy as np

from pennylane import math


def _vector_jacobian_product(dy, jac):
    """Compute the vector-Jacobian product for a given
    vector of gradient outputs dy and a Jacobian Jac"""
    dy_row = math.reshape(dy, [-1])
    return math.tensordot(jac, dy_row, [[0], [0]])


def vjp(tape, dy, gradient_fn):
    """Generate the gradient tapes and processing function required to compute
    the vector-Jacobian products of a tape.

    Args:
        tape (.QuantumTape): quantum tape to differentiate
        dy (tensor_like): Gradient-output vector`. Must have shape
            matching the output shape of the corresponding tape.
        gradient_fn (callable): the gradient transform to use to differentiate
            the tape

    Returns:
        tensor_like or None: Vector-Jacobian product. Returns None if the tape
        has no trainable parameters.

    **Example**

    Consider the following Torch-compatible quantum tape:

    .. code-block:: python

        import torch
        from pennylane.interfaces.torch import TorchInterface

        x = torch.tensor([[0.1, 0.2, 0.3],
                          [0.4, 0.5, 0.6]], requires_grad=True, dtype=torch.float64)

        with TorchInterface.apply(qml.tape.JacobianTape()) as tape:
            qml.RX(x[0, 0], wires=0)
            qml.RY(x[0, 1], wires=1)
            qml.RZ(x[0, 2], wires=0)
            qml.CNOT(wires=[0, 1])
            qml.RX(x[1, 0], wires=1)
            qml.RY(x[1, 1], wires=0)
            qml.RZ(x[1, 2], wires=1)
            qml.expval(qml.PauliZ(0))
            qml.probs(wires=1)

    We can use the ``vjp`` function to compute the vector-Jacobian product,
    given a gradient-output vector ``dy``:

    >>> dy = torch.tensor([1., 1., 1.], dtype=torch.float64)
    >>> vjp_tapes, fn = qml.gradients.vjp(tape, dy, qml.gradients.param_shift)

    Note that ``dy`` has shape ``(3,)``, matching the output dimension of the tape
    (1 expectation and 2 probability values).

    Executing the VJP tapes, and applying the processing function:

    >>> dev = qml.device("default.qubit", wires=2)
    >>> vjp = fn([t.execute(dev) for t in vjp_tapes])
    >>> vjp
    tensor([-0.6069, -0.0451,  0.0451, -0.0139, -0.2809,  0.2809],
           dtype=torch.float64, grad_fn=<ViewBackward>)

    The output VJP is also differentiable with respect to the tape parameters:

    >>> cost = torch.sum(vjp)
    >>> cost.backward()
    >>> x.grad
    tensor([[-1.1025e+00, -2.0554e-01, -1.4917e-01],
            [-1.9429e-09, -9.1580e-01,  1.3878e-09]], dtype=torch.float64)
    """
    # t._par_info = {}
    # t._update()
    num_params = len(tape.trainable_params)

    if num_params == 0:
        # The tape has no trainable parameters; the VJP
        # is simply none.
        return [], lambda _: None

    if math.allclose(dy, 0):
        # If the dy vector is zero, then the
        # corresponding element of the VJP will be zero,
        # and we can avoid a quantum computation.
        return [], lambda _: math.convert_like(np.zeros([num_params]), dy)

    gradient_tapes, fn = gradient_fn(tape)

    def processing_fn(results):
        # postprocess results to compute the Jacobian
        jac = fn(results)
        return _vector_jacobian_product(dy, jac)

    return gradient_tapes, processing_fn


def batch_vjp(tapes, dys, gradient_fn, reduction="append"):
    """Generate the gradient tapes and processing function required to compute
    the vector-Jacobian products of a batch of tapes.

    Args:
        tapes (Sequence[.QuantumTape]): sequence of quantum tapes to differentiate
        dys (Sequence[tensor_like]): Sequence of gradient-output vectors ``dy``. Must be the
            same length as ``tapes``. Each ``dy`` tensor should have shape
            matching the output shape of the corresponding tape.
        gradient_fn (callable): the gradient transform to use to differentiate
            the tapes
        reduction (str): Determines how the vector-Jacobian products are returned.
            If ``append``, then the output of the function will be of the form
            ``List[tensor_like]``, with each element corresponding to the VJP of each
            input tape. If ``extend``, then the output VJPs will be concatenated.

    Returns:
        List[tensor_like or None]: list of vector-Jacobian products. ``None`` elements corresponds
        to tapes with no trainable parameters.

    **Example**

    Consider the following Torch-compatible quantum tapes:

    .. code-block:: python

        x = torch.tensor([[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]], requires_grad=True, dtype=torch.float64)

        def ansatz(x):
            qml.RX(x[0, 0], wires=0)
            qml.RY(x[0, 1], wires=1)
            qml.RZ(x[0, 2], wires=0)
            qml.CNOT(wires=[0, 1])
            qml.RX(x[1, 0], wires=1)
            qml.RY(x[1, 1], wires=0)
            qml.RZ(x[1, 2], wires=1)

        with TorchInterface.apply(qml.tape.JacobianTape()) as tape1:
            ansatz(x)
            qml.expval(qml.PauliZ(0))
            qml.probs(wires=1)

        with TorchInterface.apply(qml.tape.JacobianTape()) as tape2:
            ansatz(x)
            qml.expval(qml.PauliZ(0) @ qml.PauliZ(1))

        tapes = [tape1, tape2]

    Both tapes share the same circuit ansatz, but have different measurement outputs.

    We can use the ``batch_vjp`` function to compute the vector-Jacobian product,
    given a list of gradient-output vectors ``dys`` per tape:

    >>> dys = [torch.tensor([1., 1., 1.], dtype=torch.float64),
    ...  torch.tensor([1.], dtype=torch.float64)]
    >>> vjp_tapes, fn = qml.gradients.batch_vjp(tapes, dys, qml.gradients.param_shift)

    Note that each ``dy`` has shape matching the output dimension of the tape
    (``tape1`` has 1 expectation and 2 probability values --- 3 outputs --- and ``tape2``
    has 1 expectation value).

    Executing the VJP tapes, and applying the processing function:

    >>> dev = qml.device("default.qubit", wires=2)
    >>> vjps = fn([t.execute(dev) for t in vjp_tapes])
    >>> vjps
    [tensor([-0.6069, -0.0451,  0.0451, -0.0139, -0.2809,  0.2809],
       dtype=torch.float64, grad_fn=<ViewBackward>),
       tensor([ 0.1739, -0.1641, -0.0054, -0.2937, -0.4008,  0.0000],
       dtype=torch.float64, grad_fn=<ViewBackward>)]

    We have two VJPs; one per tape. Each one corresponds to the number of parameters
    on the tapes (6).

    The output VJPs are also differentiable with respect to the tape parameters:

    >>> cost = torch.sum(vjps[0] + vjps[1])
    >>> cost.backward()
    >>> x.grad
    tensor([[-4.7924e-01, -9.0857e-01, -2.4198e-01],
            [-9.2973e-02, -1.0772e+00,  4.7184e-09]], dtype=torch.float64)
    """
    reshape_info = []
    gradient_tapes = []
    processing_fns = []

    # Loop through the tapes and dys vector
    for tape, dy in zip(tapes, dys):
        g_tapes, fn = vjp(tape, dy, gradient_fn)

        reshape_info.append(len(g_tapes))
        processing_fns.append(fn)
        gradient_tapes.extend(g_tapes)

    def processing_fn(results):
        vjps = []
        start = 0

        for t_idx in range(len(tapes)):
            # extract the correct results from the flat list
            res_len = reshape_info[t_idx]
            res_t = results[start : start + res_len]
            start += res_len

            # postprocess results to compute the VJP
            vjp_ = processing_fns[t_idx](res_t)

            if vjp_ is None:
                vjps.append(None)
                continue

            getattr(vjps, reduction)(vjp_)

        return vjps

    return gradient_tapes, processing_fn