# DPSpice Theoretical Reference Library

A curated collection of foundational papers, mathematical formulations, and theoretical concepts underpinning modern power system simulation. Each entry includes the seminal reference, core equations, conceptual explanation, and applicability to DPSpice.

---

## Table of Contents

1. [Dynamic Phasor Method](#1-dynamic-phasor-method)
2. [Newton-Raphson Power Flow](#2-newton-raphson-power-flow)
3. [Kron Reduction](#3-kron-reduction)
4. [Voltage Stability Analysis](#4-voltage-stability-analysis)
5. [Small-Signal Stability](#5-small-signal-stability)
6. [Transient Stability](#6-transient-stability)
7. [Sparse Matrix Techniques](#7-sparse-matrix-techniques)
8. [Network Equivalencing](#8-network-equivalencing)
9. [Instantaneous Dynamic Phasor (IDP)](#9-instantaneous-dynamic-phasor-idp)
10. [State Estimation and PMU](#10-state-estimation-and-pmu)

---

## 1. Dynamic Phasor Method

### Seminal References

- **S. R. Sanders, J. M. Noworolski, X. Z. Liu, and G. C. Verghese**, "Generalized Averaging Method for Power Conversion Circuits," *IEEE Transactions on Power Electronics*, vol. 6, no. 2, pp. 251--259, Apr. 1991. DOI: [10.1109/63.76811](https://doi.org/10.1109/63.76811)

- **P. Mattavelli, A. M. Stankovic, and G. C. Verghese**, "SSR Analysis with Dynamic Phasor Model of Thyristor-Controlled Series Capacitor," *IEEE Transactions on Power Systems*, vol. 14, no. 1, pp. 200--208, Feb. 1999. DOI: [10.1109/59.744534](https://doi.org/10.1109/59.744534)

- **T. H. Demiray**, "Simulation of Power System Dynamics using Dynamic Phasor Models," Ph.D. dissertation, Diss. ETH No. 17607, Swiss Federal Institute of Technology (ETH) Zurich, 2008. DOI: [10.3929/ethz-a-005566449](https://doi.org/10.3929/ethz-a-005566449)

- **A. M. Stankovic, S. R. Sanders, and T. Aydin**, "Dynamic Phasors in Modeling and Analysis of Unbalanced Polyphase AC Machines," *IEEE Transactions on Energy Conversion*, vol. 17, no. 1, pp. 107--113, Mar. 2002. DOI: [10.1109/60.986446](https://doi.org/10.1109/60.986446)

### Core Mathematical Formulation

The dynamic phasor method is built on the time-varying Fourier decomposition of quasi-periodic signals. Given a waveform $x(\tau)$ observed over a sliding window $[\tau - T, \tau]$ of period $T = 2\pi / \omega_0$, the $k$-th dynamic phasor (Fourier coefficient) is defined as:

$$\langle x \rangle_k (\tau) = \frac{1}{T} \int_{\tau - T}^{\tau} x(t) \, e^{-jk\omega_0 t} \, dt$$

The original signal is reconstructed from its dynamic phasors via the Fourier synthesis:

$$x(t) = \sum_{k=-\infty}^{\infty} \langle x \rangle_k (t) \, e^{jk\omega_0 t}$$

**Differentiation Property.** The time derivative of a signal maps to a shifted derivative of its dynamic phasors:

$$\left\langle \frac{dx}{dt} \right\rangle_k = \frac{d\langle x \rangle_k}{dt} + jk\omega_0 \langle x \rangle_k$$

This is the key identity: the $jk\omega_0$ term "shifts" out the carrier frequency, so the dynamic phasor $\langle x \rangle_k$ varies slowly even when $x(t)$ oscillates at $\omega_0$. This enables much larger simulation time steps.

**Convolution Property.** The product of two signals in the time domain maps to a discrete convolution of their dynamic phasors:

$$\langle xy \rangle_k = \sum_{l=-\infty}^{\infty} \langle x \rangle_l \, \langle y \rangle_{k-l}$$

### Concept

The dynamic phasor method generalizes the classical phasor representation by allowing Fourier coefficients to vary in time. In traditional phasor analysis (used in steady-state power flow), sinusoidal quantities are represented by constant complex numbers. In transient simulation, EMT programs solve differential equations at time steps on the order of microseconds to capture the full waveform ($\Delta t \sim 50\,\mu s$ at 50/60 Hz). The dynamic phasor method occupies the middle ground: by extracting time-varying envelopes of the dominant harmonic components, the carrier frequency is removed from the equations. The resulting dynamic phasor state variables evolve on the time scale of the transient envelope, not the carrier cycle, allowing time steps 10--100x larger than EMT methods while retaining accuracy for electromechanical and low-frequency electromagnetic phenomena.

The approach was first formalized by Sanders et al. (1991) for power electronics converters, extended to power systems by Mattavelli, Stankovic, and Verghese in the late 1990s, and comprehensively applied to multi-machine power systems by Demiray (2008) in his ETH Zurich dissertation.

### Application to DPSpice

DPSpice uses the dynamic phasor method as its core simulation engine. The fundamental harmonic ($k = 1$) dynamic phasor captures the dominant AC behavior of generators, transformers, transmission lines, and loads. Higher harmonics ($k = 0, 2, 3, \ldots$) can be selectively included for power electronics devices (inverters, FACTS). The differentiation property enables DPSpice to formulate network differential-algebraic equations (DAEs) in the slowly varying phasor domain, permitting time steps of 1--10 ms compared to the 20--50 $\mu$s steps required by conventional EMT simulators. This is the architectural foundation for DPSpice's real-time simulation capability in the browser.

---

## 2. Newton-Raphson Power Flow

### Seminal References

- **W. F. Tinney and C. E. Hart**, "Power Flow Solution by Newton's Method," *IEEE Transactions on Power Apparatus and Systems*, vol. PAS-86, no. 11, pp. 1449--1460, Nov. 1967. DOI: [10.1109/TPAS.1967.291823](https://doi.org/10.1109/TPAS.1967.291823)

- **B. Stott and O. Alsac**, "Fast Decoupled Load Flow," *IEEE Transactions on Power Apparatus and Systems*, vol. PAS-93, no. 3, pp. 859--869, May 1974. DOI: [10.1109/TPAS.1974.293985](https://doi.org/10.1109/TPAS.1974.293985)

- **V. Ajjarapu and C. Christy**, "The Continuation Power Flow: A Tool for Steady State Voltage Stability Analysis," *IEEE Transactions on Power Systems*, vol. 7, no. 1, pp. 416--423, Feb. 1992. DOI: [10.1109/59.141737](https://doi.org/10.1109/59.141737)

### Core Mathematical Formulation

**Power Injection Equations.** At bus $i$ of an $n$-bus network with admittance matrix $Y_{ik} = G_{ik} + jB_{ik}$:

$$P_i = \sum_{k=1}^{n} V_i V_k \left[ G_{ik} \cos(\delta_i - \delta_k) + B_{ik} \sin(\delta_i - \delta_k) \right]$$

$$Q_i = \sum_{k=1}^{n} V_i V_k \left[ G_{ik} \sin(\delta_i - \delta_k) - B_{ik} \cos(\delta_i - \delta_k) \right]$$

**Newton-Raphson Iteration.** The mismatch equations are linearized and solved iteratively:

$$\begin{bmatrix} \Delta P \\ \Delta Q \end{bmatrix} = \begin{bmatrix} H & N \\ M & L \end{bmatrix} \begin{bmatrix} \Delta \boldsymbol{\delta} \\ \Delta \mathbf{V} / \mathbf{V} \end{bmatrix}$$

where $H_{ij} = \partial P_i / \partial \delta_j$, $N_{ij} = V_j \, \partial P_i / \partial V_j$, $M_{ij} = \partial Q_i / \partial \delta_j$, $L_{ij} = V_j \, \partial Q_i / \partial V_j$.

The update at iteration $r$:

$$\boldsymbol{\delta}^{(r+1)} = \boldsymbol{\delta}^{(r)} + \Delta \boldsymbol{\delta}^{(r)}, \qquad \mathbf{V}^{(r+1)} = \mathbf{V}^{(r)} + \Delta \mathbf{V}^{(r)}$$

**Fast Decoupled Load Flow (Stott-Alsac).** Exploiting the weak coupling between $P$-$\delta$ and $Q$-$V$:

$$\Delta P / V = B' \, \Delta \boldsymbol{\delta}$$

$$\Delta Q / V = B'' \, \Delta \mathbf{V}$$

where $B'$ and $B''$ are constant, sparse susceptance matrices computed once and factored. Each half-iteration requires only a forward/backward substitution, making this method extremely fast for large networks.

### Concept

The Newton-Raphson (NR) power flow is the industry standard for computing the steady-state operating point of a power system. Given specified generation, load, and voltage setpoints, the NR method iteratively solves the nonlinear algebraic power balance equations. Tinney and Hart (1967) demonstrated that NR converges in approximately 5 iterations regardless of system size, with each iteration involving the formation and factorization of the Jacobian matrix. The quadratic convergence of NR is its primary advantage over earlier Gauss-Seidel methods.

Stott and Alsac (1974) introduced the fast decoupled load flow (FDLF), which exploits the physical decoupling between real power / angle and reactive power / voltage in transmission networks. By using constant, pre-factored susceptance matrices, FDLF reduces each iteration to two sparse triangular solves, achieving convergence in 4--7 iterations at a fraction of the cost of a full NR iteration.

### Application to DPSpice

DPSpice implements the full Newton-Raphson power flow as the initial condition solver for dynamic simulations. Before any transient simulation begins, the NR power flow computes the steady-state voltage magnitudes and angles at every bus, which serve as the initial values for the dynamic phasor state variables. DPSpice also provides standalone power flow analysis as a core feature, with the Jacobian matrix reused for sensitivity analysis and contingency screening. The fast decoupled variant is available as a user-selectable option for rapid approximate solutions on larger networks.

---

## 3. Kron Reduction

### Seminal References

- **F. Dorfler and F. Bullo**, "Kron Reduction of Graphs with Applications to Electrical Networks," *IEEE Transactions on Circuits and Systems I: Regular Papers*, vol. 60, no. 1, pp. 150--163, Jan. 2013. DOI: [10.1109/TCSI.2012.2215780](https://doi.org/10.1109/TCSI.2012.2215780)

- **G. Kron**, *Tensor Analysis of Networks*, John Wiley & Sons, New York, 1939.

### Core Mathematical Formulation

Consider the network admittance equation $\mathbf{I} = \mathbf{Y} \mathbf{V}$ partitioned into boundary nodes $\alpha$ (to retain) and interior nodes $\beta$ (to eliminate):

$$\begin{bmatrix} \mathbf{I}_\alpha \\ \mathbf{I}_\beta \end{bmatrix} = \begin{bmatrix} \mathbf{Y}_{\alpha\alpha} & \mathbf{Y}_{\alpha\beta} \\ \mathbf{Y}_{\beta\alpha} & \mathbf{Y}_{\beta\beta} \end{bmatrix} \begin{bmatrix} \mathbf{V}_\alpha \\ \mathbf{V}_\beta \end{bmatrix}$$

Setting $\mathbf{I}_\beta = 0$ (no current injection at interior nodes) and eliminating $\mathbf{V}_\beta$:

$$\mathbf{V}_\beta = -\mathbf{Y}_{\beta\beta}^{-1} \mathbf{Y}_{\beta\alpha} \mathbf{V}_\alpha$$

Substituting back yields the **Kron-reduced admittance matrix** (Schur complement):

$$\mathbf{Y}_{\text{red}} = \mathbf{Y}_{\alpha\alpha} - \mathbf{Y}_{\alpha\beta} \, \mathbf{Y}_{\beta\beta}^{-1} \, \mathbf{Y}_{\beta\alpha}$$

**Element-wise Gaussian Elimination.** When eliminating node $k$:

$$Y_{ij}^{\text{new}} = Y_{ij}^{\text{old}} - \frac{Y_{ik}^{\text{old}} \, Y_{kj}^{\text{old}}}{Y_{kk}^{\text{old}}}$$

This is the classical Kron reduction formula, equivalent to one step of Gaussian elimination on the admittance matrix.

### Concept

Kron reduction is the process of eliminating passive (zero-injection) nodes from a network while preserving the electrical behavior as seen from the remaining nodes. Originating in Gabriel Kron's tensor analysis of networks (1939), the method relies on the Schur complement of the admittance matrix. Dorfler and Bullo (2013) provided the modern graph-theoretic treatment, proving key properties: Kron reduction preserves the Laplacian structure, maintains network connectivity, and is equivalent to computing the effective impedance between retained nodes.

In power systems, Kron reduction is used ubiquitously to reduce the full bus admittance matrix to a smaller system involving only generator internal nodes, enabling transient stability analysis on a reduced-order model. The reduction is exact for linear networks and approximate (but highly accurate) for mildly nonlinear load models.

### Application to DPSpice

DPSpice implements Kron reduction to generate reduced-order models for transient stability simulation. After computing the full admittance matrix from the network topology, all load buses (PQ buses with no dynamic equipment) are eliminated via the Schur complement, producing a dense but much smaller admittance matrix connecting only generator internal nodes. This dramatically reduces the system dimension for dynamic simulation while maintaining exact equivalence at the generator terminals. The hierarchical grid navigation feature in DPSpice also uses Kron reduction to display simplified views of large networks at different zoom levels.

---

## 4. Voltage Stability Analysis

### Seminal References

- **V. Ajjarapu and C. Christy**, "The Continuation Power Flow: A Tool for Steady State Voltage Stability Analysis," *IEEE Transactions on Power Systems*, vol. 7, no. 1, pp. 416--423, Feb. 1992. DOI: [10.1109/59.141737](https://doi.org/10.1109/59.141737)

- **P. Kundur**, *Power System Stability and Control*, McGraw-Hill, New York, 1994. ISBN: 007035958X.

- **T. Van Cutsem and C. Vournas**, *Voltage Stability of Electric Power Systems*, Springer, 1998. ISBN: 978-0-7923-8139-6.

### Core Mathematical Formulation

**Continuation Power Flow.** The standard power flow equations are augmented with a loading parameter $\lambda$:

$$\mathbf{F}(\boldsymbol{\delta}, \mathbf{V}, \lambda) = \begin{bmatrix} P_i^{\text{gen}} + \lambda \, \Delta P_i^{\text{gen}} - P_i^{\text{load}} - \lambda \, \Delta P_i^{\text{load}} - P_i^{\text{calc}}(\boldsymbol{\delta}, \mathbf{V}) \\ Q_i^{\text{gen}} - Q_i^{\text{load}} - \lambda \, \Delta Q_i^{\text{load}} - Q_i^{\text{calc}}(\boldsymbol{\delta}, \mathbf{V}) \end{bmatrix} = \mathbf{0}$$

At $\lambda = 0$, the system operates at base case. As $\lambda$ increases toward $\lambda_{\text{max}}$, the system traces a PV curve until reaching the nose point (saddle-node bifurcation).

**Predictor Step** (tangent vector):

$$\begin{bmatrix} \mathbf{F}_{\mathbf{x}} & \mathbf{F}_\lambda \\ \mathbf{e}_k^T & 0 \end{bmatrix} \begin{bmatrix} d\mathbf{x} \\ d\lambda \end{bmatrix} = \begin{bmatrix} \mathbf{0} \\ 1 \end{bmatrix}$$

where $\mathbf{x} = [\boldsymbol{\delta}, \mathbf{V}]^T$ and $\mathbf{e}_k$ selects the continuation parameter.

**Corrector Step** (perpendicular intersection or local parameterization):

$$\begin{bmatrix} \mathbf{F}(\mathbf{x}, \lambda) \\ x_k - x_k^{\text{predicted}} \end{bmatrix} = \mathbf{0}$$

**Voltage Stability Margin:**

$$\text{VSM} = \frac{\lambda_{\text{max}} - \lambda_0}{\lambda_0} \times 100\%$$

### Concept

Voltage stability analysis determines how close a power system operates to the point of voltage collapse. The PV curve (power-voltage curve) traces the voltage at a critical bus as system loading increases; the apex of this curve is the "nose point," beyond which no power flow solution exists. The QV curve shows the reactive power margin at a bus --- the distance between the operating point and the point where reactive support is exhausted.

Ajjarapu and Christy (1992) developed the continuation power flow (CPF) method, which overcomes the fundamental limitation of conventional NR power flow at the nose point: the Jacobian becomes singular. CPF uses a predictor-corrector scheme with local parameterization to smoothly trace the entire PV curve, including the lower (unstable) portion. The method remains numerically well-conditioned at and around the critical point.

### Application to DPSpice

DPSpice implements continuation power flow for voltage stability assessment. Users can define a loading direction (uniform scaling or specific bus loading patterns) and DPSpice traces the PV curve, automatically detecting the nose point and computing the voltage stability margin. The PV and QV curves are rendered interactively in the web interface, allowing engineers to identify weak buses and assess the impact of contingencies. This feature is critical for DPSpice's value proposition in grid planning and operational security assessment.

---

## 5. Small-Signal Stability

### Seminal References

- **P. Kundur**, *Power System Stability and Control*, McGraw-Hill, New York, 1994. Chapters 12--13. ISBN: 007035958X.

- **I. J. Perez-Arriaga, G. C. Verghese, and F. C. Schweppe**, "Selective Modal Analysis with Applications to Electric Power Systems, Part I: Heuristic Introduction," *IEEE Transactions on Power Apparatus and Systems*, vol. PAS-101, no. 9, pp. 3117--3125, Sep. 1982. DOI: [10.1109/TPAS.1982.317524](https://doi.org/10.1109/TPAS.1982.317524)

- **F. L. Pagola, I. J. Perez-Arriaga, and G. C. Verghese**, "On Sensitivities, Residues and Participations: Applications to Oscillatory Stability Analysis and Control," *IEEE Transactions on Power Systems*, vol. 4, no. 1, pp. 278--285, Feb. 1989. DOI: [10.1109/59.32489](https://doi.org/10.1109/59.32489)

### Core Mathematical Formulation

**Linearized State Equations.** Around an equilibrium point, the power system DAEs are linearized:

$$\Delta \dot{\mathbf{x}} = \mathbf{A} \, \Delta \mathbf{x} + \mathbf{B} \, \Delta \mathbf{u}$$

$$\Delta \mathbf{y} = \mathbf{C} \, \Delta \mathbf{x} + \mathbf{D} \, \Delta \mathbf{u}$$

The system is small-signal stable if and only if all eigenvalues $\lambda_i$ of the state matrix $\mathbf{A}$ have negative real parts: $\text{Re}(\lambda_i) < 0 \; \forall \, i$.

**Eigenvalue Decomposition.** For complex eigenvalues $\lambda_i = \sigma_i \pm j\omega_i$:

- **Oscillation frequency:** $f_i = \omega_i / (2\pi)$ Hz
- **Damping ratio:** $\zeta_i = -\sigma_i / \sqrt{\sigma_i^2 + \omega_i^2}$

A mode is considered adequately damped if $\zeta_i > 0.05$ (5% damping ratio), per common industry practice.

**Participation Factors.** The participation factor of the $k$-th state variable in the $i$-th mode is:

$$p_{ki} = \phi_{ki} \, \psi_{ik}$$

where $\phi_{ki}$ is the $k$-th element of the right eigenvector of mode $i$, and $\psi_{ik}$ is the $k$-th element of the corresponding left eigenvector. Participation factors are dimensionless and identify which generators participate most strongly in each oscillatory mode.

### Concept

Small-signal stability analysis examines the system's response to small perturbations around an operating point. The nonlinear DAEs are linearized to obtain the state matrix $\mathbf{A}$, whose eigenvalues characterize the system modes. Complex eigenvalue pairs correspond to oscillatory modes (electromechanical oscillations between generators), while real eigenvalues correspond to non-oscillatory modes. Low-frequency oscillations (0.1--2 Hz) are classified as local modes (one generator swinging against the rest of the system) or inter-area modes (groups of generators in one region swinging against another).

Perez-Arriaga, Verghese, and Schweppe (1982) introduced selective modal analysis and participation factors, which became the standard tool for identifying the physical origin of each mode and for placing power system stabilizers (PSS). The PSS adds damping torque through the excitation system using a washout filter and lead-lag compensation stages, with parameters tuned to shift critical eigenvalues leftward in the complex plane.

### Application to DPSpice

DPSpice computes the linearized state matrix $\mathbf{A}$ from the dynamic phasor model at the power flow solution. Eigenvalues and participation factors are computed and displayed in an interactive eigenvalue plot (complex plane), with oscillatory modes color-coded by damping ratio. Users can identify poorly damped modes, trace them to specific generators via participation factors, and design PSS compensation. The dynamic phasor formulation naturally provides the linearized system in the frequency-shifted domain, making the eigenvalue computation directly applicable without additional transformation.

---

## 6. Transient Stability

### Seminal References

- **P. Kundur**, *Power System Stability and Control*, McGraw-Hill, New York, 1994. Chapters 2, 10--11. ISBN: 007035958X.

- **P. M. Anderson and A. A. Fouad**, *Power System Control and Stability*, 2nd ed., IEEE Press / Wiley-Interscience, 2003. ISBN: 978-0-471-23862-1.

- **H. W. Dommel**, "Digital Computer Solution of Electromagnetic Transients in Single- and Multiphase Networks," *IEEE Transactions on Power Apparatus and Systems*, vol. PAS-88, no. 4, pp. 388--399, Apr. 1969. DOI: [10.1109/TPAS.1969.292459](https://doi.org/10.1109/TPAS.1969.292459)

### Core Mathematical Formulation

**Swing Equation.** The electromechanical dynamics of the $i$-th synchronous machine:

$$\frac{2H_i}{\omega_s} \frac{d^2\delta_i}{dt^2} = P_{m,i} - P_{e,i} - D_i \frac{d\delta_i}{dt}$$

where $H_i$ is the inertia constant (seconds), $\omega_s$ is synchronous speed (rad/s), $\delta_i$ is the rotor angle, $P_{m,i}$ is mechanical power input, $P_{e,i}$ is electrical power output, and $D_i$ is the damping coefficient.

In state-variable form (letting $\omega_i = d\delta_i / dt$):

$$\frac{d\delta_i}{dt} = \omega_i - \omega_s$$

$$\frac{2H_i}{\omega_s} \frac{d\omega_i}{dt} = P_{m,i} - P_{e,i} - D_i (\omega_i - \omega_s)$$

**Equal Area Criterion (single machine infinite bus).** The system is transiently stable if:

$$\int_{\delta_0}^{\delta_{\text{cr}}} (P_m - P_e^{\text{fault}}) \, d\delta \leq \int_{\delta_{\text{cr}}}^{\delta_{\text{max}}} (P_e^{\text{post}} - P_m) \, d\delta$$

The left integral is the accelerating area $A_{\text{acc}}$; the right integral is the maximum available decelerating area $A_{\text{dec}}$. The critical clearing angle $\delta_{\text{cr}}$ is where $A_{\text{acc}} = A_{\text{dec}}$:

$$\delta_{\text{cr}} = \cos^{-1} \left[ \frac{P_m (\delta_{\text{max}} - \delta_0) - P_{\text{max}}^{\text{post}} \cos\delta_{\text{max}} + P_{\text{max}}^{\text{fault}} \cos\delta_0}{P_{\text{max}}^{\text{post}} - P_{\text{max}}^{\text{fault}}} \right]$$

**Trapezoidal Rule (Dommel's method).** For numerical integration of $\dot{x} = f(x,t)$:

$$x(t + \Delta t) = x(t) + \frac{\Delta t}{2} \left[ f(x(t+\Delta t), t+\Delta t) + f(x(t), t) \right]$$

This implicit A-stable method is the foundation of all EMTP-type programs and is also used in DPSpice's time-domain solver.

### Concept

Transient stability assesses whether synchronous machines maintain synchronism following a large disturbance (fault, line trip, generator loss). The swing equation governs rotor angle dynamics: when a fault reduces electrical power output while mechanical input remains constant, the rotor accelerates. If the fault is cleared quickly enough, the rotor decelerates and settles to a new equilibrium. If not, the rotor angle diverges and the machine loses synchronism.

The equal area criterion provides elegant graphical insight for single-machine-infinite-bus systems: stability requires that the kinetic energy gained during acceleration (proportional to area under the accelerating power curve) can be absorbed during deceleration. For multi-machine systems, numerical integration of the coupled swing equations is required. Dommel (1969) established the trapezoidal rule as the standard integration method for electromagnetic transient simulation, valued for its A-stability (no numerical instability regardless of step size) and second-order accuracy.

### Application to DPSpice

DPSpice solves the swing equations in the dynamic phasor domain, where the electrical power $P_{e,i}$ is computed from the dynamic phasor network solution rather than instantaneous EMT quantities. The trapezoidal rule is used for time integration of both the machine differential equations and the network algebraic equations. For educational use, DPSpice provides interactive equal area criterion visualization for SMIB systems, where users can adjust fault duration and observe the relationship between accelerating and decelerating areas in real time. For multi-machine transient stability, DPSpice computes and displays rotor angle trajectories, speed deviations, and power transfer curves.

---

## 7. Sparse Matrix Techniques

### Seminal References

- **W. F. Tinney and J. W. Walker**, "Direct Solutions of Sparse Network Equations by Optimally Ordered Triangular Factorization," *Proceedings of the IEEE*, vol. 55, no. 11, pp. 1801--1809, Nov. 1967. DOI: [10.1109/PROC.1967.6011](https://doi.org/10.1109/PROC.1967.6011)

- **T. A. Davis and E. Palamadai Natarajan**, "Algorithm 907: KLU, A Direct Sparse Solver for Circuit Simulation Problems," *ACM Transactions on Mathematical Software*, vol. 37, no. 3, Article 36, Sep. 2010. DOI: [10.1145/1824801.1824814](https://doi.org/10.1145/1824801.1824814)

- **T. A. Davis**, "Algorithm 832: UMFPACK V4.3 -- An Unsymmetric-Pattern Multifrontal Method," *ACM Transactions on Mathematical Software*, vol. 30, no. 2, pp. 196--199, Jun. 2004. DOI: [10.1145/992200.992206](https://doi.org/10.1145/992200.992206)

### Core Mathematical Formulation

**Sparse LU Factorization.** The admittance matrix $\mathbf{Y}$ is factored as:

$$\mathbf{P} \mathbf{Y} \mathbf{Q} = \mathbf{L} \mathbf{U}$$

where $\mathbf{P}$ and $\mathbf{Q}$ are permutation matrices (chosen to minimize fill-in), $\mathbf{L}$ is unit lower triangular, and $\mathbf{U}$ is upper triangular. The system $\mathbf{Y} \mathbf{V} = \mathbf{I}$ is then solved by:

$$\mathbf{L} \mathbf{z} = \mathbf{P} \mathbf{I} \quad \text{(forward substitution)}$$

$$\mathbf{U} \mathbf{w} = \mathbf{z} \quad \text{(backward substitution)}$$

$$\mathbf{V} = \mathbf{Q} \mathbf{w}$$

**Optimal Ordering (Tinney Schemes).** Three heuristic ordering strategies minimize fill-in:

- **Scheme 1 (Static Minimum Degree):** Order nodes by ascending degree count at each step.
- **Scheme 2 (Dynamic Minimum Degree):** Recount degrees after each elimination, choosing the minimum.
- **Scheme 3 (Minimum Local Fill):** At each step, eliminate the node that creates the fewest new non-zeros.

**Fill-in Count.** After eliminating node $k$ with $d_k$ connections, the maximum new fill-in entries are:

$$\text{fill}(k) \leq \frac{d_k(d_k - 1)}{2} - e_k$$

where $e_k$ is the number of existing edges among the neighbors of $k$.

### Concept

Power system matrices are extremely sparse: a 10,000-bus system has an admittance matrix with roughly 99.97% zeros. Exploiting this sparsity is essential for computational efficiency. Tinney and Walker (1967) demonstrated that the order in which nodes are eliminated during Gaussian elimination dramatically affects fill-in (new non-zero entries created during factorization). Their optimal ordering schemes reduce the factorized matrix from potentially dense to nearly as sparse as the original, enabling direct solution of systems with thousands or tens of thousands of buses.

KLU (Davis and Natarajan, 2010) is a sparse direct solver specifically designed for circuit simulation matrices. It uses block triangular form (BTF) decomposition to break the sparse LU problem into many smaller subproblems, combined with approximate minimum degree ordering within each block. KLU is the default solver in Sandia's Xyce circuit simulator and is well-suited to the extremely sparse, unsymmetric matrices arising in dynamic phasor simulation.

UMFPACK (Davis, 2004) uses an unsymmetric-pattern multifrontal method, combining column pre-ordering with right-looking numerical factorization. It is built into MATLAB as the default sparse solver.

### Application to DPSpice

DPSpice's C++ engine relies on sparse direct solvers for both power flow (Jacobian factorization) and dynamic simulation (network admittance matrix solution at each time step). The admittance matrix is formed in compressed sparse column (CSC) format, ordered using approximate minimum degree (AMD), and factored using LU decomposition. For the dynamic phasor formulation, the admittance matrix is complex-valued but retains the same sparsity pattern as the real-valued power flow matrix, so the same sparse storage and ordering techniques apply directly. Refactorization is performed only when the network topology changes (switching events); otherwise, only the numerical values are updated, reusing the symbolic factorization.

---

## 8. Network Equivalencing

### Seminal References

- **J. B. Ward**, "Equivalent Circuits for Power Flow Studies," *AIEE Transactions on Power Apparatus and Systems*, vol. 68, no. 1, pp. 373--382, 1949. DOI: [10.1109/T-AIEE.1949.5059947](https://doi.org/10.1109/T-AIEE.1949.5059947)

- **P. Dimo**, *Nodal Analysis of Power Systems*, Abacus Press, Tunbridge Wells, UK, 1975. (Introduces the REI equivalent method.)

- **A. Monticelli, S. Deckmann, A. Garcia, and B. Stott**, "Real-Time External Equivalents for Static Security Analysis," *IEEE Transactions on Power Apparatus and Systems*, vol. PAS-98, no. 2, pp. 498--508, Mar. 1979. DOI: [10.1109/TPAS.1979.319404](https://doi.org/10.1109/TPAS.1979.319404)

### Core Mathematical Formulation

**Ward Equivalent.** Partition the system into study area (S) and external area (E) connected at boundary buses (B). The Ward equivalent eliminates external buses using Kron reduction:

$$\mathbf{Y}_{\text{Ward}} = \mathbf{Y}_{BB} - \mathbf{Y}_{BE} \, \mathbf{Y}_{EE}^{-1} \, \mathbf{Y}_{EB}$$

with equivalent current injections at boundary buses:

$$\mathbf{I}_{\text{eq}} = \mathbf{I}_B - \mathbf{Y}_{BE} \, \mathbf{Y}_{EE}^{-1} \, \mathbf{I}_E$$

**REI (Radial Equivalent Independent) Equivalent.** Aggregate all external generators and loads into a single fictitious node connected to boundary buses through equivalent impedances. The REI preserves the total power injection:

$$P_{\text{REI}} + jQ_{\text{REI}} = \sum_{k \in E} (P_k + jQ_k)$$

The equivalent impedance connecting the REI node to each boundary bus $b$ is:

$$Z_{b,\text{REI}} = \frac{|V_b|^2}{S_b^*}$$

where $S_b$ is the power flowing from the external area into boundary bus $b$.

**Extended Ward Equivalent.** Combines Ward reduction with PV bus representation at boundary buses to maintain voltage regulation:

$$\mathbf{Y}_{\text{ext}} = \mathbf{Y}_{\text{Ward}} + \text{diag}(Y_{\text{shunt},b})$$

### Concept

Network equivalencing reduces a large external system to a compact representation while preserving the electrical behavior at the boundary with the study area. The Ward equivalent (1949) applies Kron reduction to the external network and represents the effect of external generators and loads as equivalent current injections at boundary buses. It is exact for linear networks at the base case operating point but loses accuracy as the system moves away from that point because the equivalent injections are fixed.

The REI equivalent (Dimo, 1975) takes a different approach: instead of eliminating nodes via Gaussian elimination, it aggregates external generation and load into fictitious "REI nodes" connected radially to boundary buses. The advantage is that REI preserves the zero-power-balance condition and can be more easily updated for different operating conditions.

The Extended Ward method (Monticelli et al., 1979) improves upon the basic Ward equivalent by maintaining voltage-controlled (PV) buses at the boundary, preserving voltage regulation effects from the external system.

### Application to DPSpice

DPSpice uses network equivalencing for two purposes. First, for large-system simulation where only a portion of the network requires detailed dynamic modeling, the rest of the system is represented by a Ward or REI equivalent at the boundary buses. This reduces the dimension of the dynamic simulation without losing accuracy at the study area boundary. Second, the hierarchical grid navigation feature uses progressive equivalencing at different zoom levels: at the highest level, entire regions are represented by equivalents; zooming in reveals progressively more detailed network models.

---

## 9. Instantaneous Dynamic Phasor (IDP)

### Seminal References

- **T. H. Demiray**, "Simulation of Power System Dynamics using Dynamic Phasor Models," Ph.D. dissertation, ETH Zurich, 2008. Chapter 4: Instantaneous Dynamic Phasors.

- **K. Strunz and E. Carlson**, "Nested Fast and Simultaneous Solution for Time-Domain Simulation of Integrating Composed Network and Machine Models," *IEEE Transactions on Power Systems*, vol. 22, no. 4, pp. 1982--1990, Nov. 2007.

- **M. Mirz, S. Vogel, G. Reinke, and A. Monti**, "DPsim -- A Dynamic Phasor Real-Time Simulator for Power Systems," *SoftwareX*, vol. 10, 100253, Jul.--Dec. 2019. DOI: [10.1016/j.softx.2019.100253](https://doi.org/10.1016/j.softx.2019.100253)

### Core Mathematical Formulation

In standard dynamic phasors, only selected harmonics $k$ are retained (typically $k \in \{-1, 0, 1\}$). The IDP method selectively includes higher-order harmonics for components that exhibit fast sub-cycle dynamics (power electronics, arc models) while keeping $k = 1$ for the bulk power system.

**Selective Harmonic Inclusion.** For a signal with $K$ retained harmonics:

$$x(t) \approx \sum_{k=-K}^{K} \langle x \rangle_k(t) \, e^{jk\omega_0 t}$$

The state dimension increases from $2n$ (for $k = \pm 1$ only) to $2n(2K+1)$ when including harmonics up to order $K$.

**Sparse IDP Formulation.** In DPSpice's sparse IDP, only selected buses/components use $K > 1$. The network admittance matrix becomes block-structured:

$$\mathbf{Y}_{\text{IDP}} = \begin{bmatrix} \mathbf{Y}^{(1,1)} & \mathbf{Y}^{(1,3)} & \cdots \\ \mathbf{Y}^{(3,1)} & \mathbf{Y}^{(3,3)} & \cdots \\ \vdots & \vdots & \ddots \end{bmatrix}$$

where $\mathbf{Y}^{(k,l)}$ represents the coupling between the $k$-th and $l$-th harmonic admittance blocks. For linear network elements, the off-diagonal blocks $\mathbf{Y}^{(k,l)}$ ($k \neq l$) are zero, and each diagonal block is the standard admittance matrix shifted to harmonic $k$:

$$\mathbf{Y}^{(k,k)} = \mathbf{G} + j\mathbf{B} + jk\omega_0 \mathbf{C}_{\text{shunt}}$$

Harmonic coupling arises only from nonlinear elements (converters, saturable transformers).

### Concept

The Instantaneous Dynamic Phasor (IDP) extends the DP method to capture sub-cycle dynamics that the fundamental-frequency DP model cannot resolve. Standard DP ($k = 1$) filters out harmonic content above the fundamental, which is acceptable for electromechanical transients but insufficient for analyzing phenomena involving power electronics switching, harmonic distortion, or sub-synchronous resonance.

IDP selectively includes higher harmonics for specific components. For example, a voltage-source converter modeled at $K = 5$ captures switching harmonics up to the 5th order, while the rest of the network remains at $K = 1$. The key insight is that higher harmonics are needed only locally (at converter terminals), not system-wide, so the computational cost increase is localized.

This "sparse" inclusion of harmonics provides a continuum between pure DP simulation (fast, low-fidelity for harmonics) and full EMT simulation (slow, full-fidelity). The simulation time step remains determined by the slowly varying envelope of the highest included harmonic, which is still much larger than the EMT time step.

### Application to DPSpice

DPSpice implements sparse IDP as a user-configurable feature. By default, the simulation runs in DP mode ($K = 1$) for maximum speed. Users can selectively enable higher harmonics on specific buses or components (e.g., $K = 3$ for an inverter-interfaced resource, $K = 5$ for a thyristor-controlled device). The admittance matrix assembler automatically constructs the appropriate block structure, and the sparse solver handles the increased dimension. This gives DPSpice the unique ability to bridge the gap between phasor and EMT simulation within a single unified framework, avoiding the need for separate EMT and phasor simulation tools.

---

## 10. State Estimation and PMU

### Seminal References

- **F. C. Schweppe and J. Wildes**, "Power System Static-State Estimation, Part I: Exact Model," *IEEE Transactions on Power Apparatus and Systems*, vol. PAS-89, no. 1, pp. 120--125, Jan. 1970. DOI: [10.1109/TPAS.1970.292678](https://doi.org/10.1109/TPAS.1970.292678)

- **F. C. Schweppe and D. B. Rom**, "Power System Static-State Estimation, Part II: Approximate Model," *IEEE Transactions on Power Apparatus and Systems*, vol. PAS-89, no. 1, pp. 125--130, Jan. 1970.

- **F. C. Schweppe**, "Power System Static-State Estimation, Part III: Implementation," *IEEE Transactions on Power Apparatus and Systems*, vol. PAS-89, no. 1, pp. 130--135, Jan. 1970.

- **A. Abur and A. G. Exposito**, *Power System State Estimation: Theory and Implementation*, Marcel Dekker / CRC Press, New York, 2004. ISBN: 0824755707.

- **A. G. Phadke and J. S. Thorp**, *Synchronized Phasor Measurements and Their Applications*, Springer, 2008. ISBN: 978-0-387-76535-8.

### Core Mathematical Formulation

**Measurement Model.** The measurement vector $\mathbf{z}$ relates to the state vector $\mathbf{x} = [\boldsymbol{\delta}, \mathbf{V}]^T$ through:

$$\mathbf{z} = \mathbf{h}(\mathbf{x}) + \mathbf{e}$$

where $\mathbf{h}(\mathbf{x})$ is the nonlinear measurement function (power flows, power injections, voltage magnitudes) and $\mathbf{e}$ is the measurement error vector with covariance $\mathbf{R} = \text{diag}(\sigma_1^2, \sigma_2^2, \ldots, \sigma_m^2)$.

**Weighted Least Squares (WLS) Objective:**

$$\min_{\mathbf{x}} \; J(\mathbf{x}) = [\mathbf{z} - \mathbf{h}(\mathbf{x})]^T \mathbf{R}^{-1} [\mathbf{z} - \mathbf{h}(\mathbf{x})]$$

**Normal Equation (Gauss-Newton iteration):**

$$\mathbf{G}(\mathbf{x}^{(r)}) \, \Delta \mathbf{x}^{(r)} = \mathbf{H}(\mathbf{x}^{(r)})^T \mathbf{R}^{-1} [\mathbf{z} - \mathbf{h}(\mathbf{x}^{(r)})]$$

where $\mathbf{H} = \partial \mathbf{h} / \partial \mathbf{x}$ is the measurement Jacobian and $\mathbf{G} = \mathbf{H}^T \mathbf{R}^{-1} \mathbf{H}$ is the gain matrix.

**Bad Data Detection.** The normalized residual for measurement $i$:

$$r_i^N = \frac{|z_i - h_i(\hat{\mathbf{x}})|}{\sqrt{R_{ii} - (\mathbf{H} \mathbf{G}^{-1} \mathbf{H}^T)_{ii}}}$$

If $r_i^N > \tau$ (threshold, typically 3.0), measurement $i$ is flagged as bad data.

**PMU Linear Measurement Model.** PMUs measure voltage phasors directly:

$$z_{\text{PMU},i} = V_i e^{j\delta_i} + e_i$$

PMU measurements are linear in the state variables (no trigonometric nonlinearity), enabling a purely linear state estimator when sufficient PMU coverage exists:

$$\hat{\mathbf{x}} = (\mathbf{H}_{\text{PMU}}^T \mathbf{R}_{\text{PMU}}^{-1} \mathbf{H}_{\text{PMU}})^{-1} \mathbf{H}_{\text{PMU}}^T \mathbf{R}_{\text{PMU}}^{-1} \mathbf{z}_{\text{PMU}}$$

### Concept

State estimation determines the best estimate of the system state (voltage magnitudes and angles at all buses) from a redundant set of noisy measurements. Schweppe (1970) formulated the problem in three landmark papers, establishing the weighted least squares approach that remains the industry standard. The WLS estimator minimizes the weighted sum of squared measurement residuals, with weights inversely proportional to measurement variance.

Bad data detection identifies erroneous measurements (instrument failures, communication errors, topology errors) by analyzing normalized residuals. Measurements with residuals exceeding a statistical threshold are removed, and the estimation is re-run.

Phasor Measurement Units (PMUs), enabled by GPS-synchronized sampling, provide direct measurements of voltage and current phasors at reporting rates of 30--60 samples per second. PMU measurements are linear in the state variables, which dramatically simplifies the estimation problem and enables real-time dynamic state estimation.

### Application to DPSpice

DPSpice could implement state estimation as a monitoring and validation layer for its dynamic simulation. By comparing simulated dynamic phasor states against PMU-like measurements (either real PMU data imported via the API or synthetic measurements from the simulation with added noise), DPSpice can demonstrate state estimation algorithms for educational purposes and validate simulation accuracy against field measurements. The WLS formulation fits naturally into DPSpice's existing sparse matrix infrastructure, as the gain matrix $\mathbf{G}$ has the same sparsity pattern as the power flow Jacobian. PMU-based linear state estimation is particularly relevant as DPSpice already operates in the phasor domain, making the measurement model directly compatible with the simulation state.

---

## Cross-Reference Matrix

| DPSpice Feature | Theoretical Foundation | Key Reference |
|---|---|---|
| Core simulation engine | Dynamic Phasor Method | Sanders 1991, Demiray 2008 |
| Power flow solver | Newton-Raphson, FDLF | Tinney & Hart 1967, Stott & Alsac 1974 |
| Network reduction | Kron Reduction | Dorfler & Bullo 2013 |
| Voltage stability tools | Continuation Power Flow | Ajjarapu & Christy 1992 |
| Eigenvalue analysis | Small-Signal Stability | Kundur 1994, Perez-Arriaga 1982 |
| Transient simulation | Swing Equation, Trapezoidal Rule | Kundur 1994, Dommel 1969 |
| Matrix solver | Sparse LU, Optimal Ordering | Tinney & Walker 1967, Davis 2010 |
| Hierarchical navigation | Network Equivalencing | Ward 1949, Dimo 1975 |
| Sub-cycle dynamics | Instantaneous Dynamic Phasor | Demiray 2008, Mirz 2019 |
| Monitoring layer | State Estimation, PMU | Schweppe 1970, Abur & Exposito 2004 |

---

## Bibliography (Alphabetical)

1. Abur, A. and Exposito, A. G. (2004). *Power System State Estimation: Theory and Implementation*. Marcel Dekker / CRC Press.
2. Ajjarapu, V. and Christy, C. (1992). The continuation power flow: a tool for steady state voltage stability analysis. *IEEE Trans. Power Syst.*, 7(1):416--423.
3. Anderson, P. M. and Fouad, A. A. (2003). *Power System Control and Stability*, 2nd ed. IEEE Press / Wiley-Interscience.
4. Davis, T. A. (2004). Algorithm 832: UMFPACK V4.3 -- an unsymmetric-pattern multifrontal method. *ACM Trans. Math. Softw.*, 30(2):196--199.
5. Davis, T. A. and Natarajan, E. P. (2010). Algorithm 907: KLU, a direct sparse solver for circuit simulation problems. *ACM Trans. Math. Softw.*, 37(3):Article 36.
6. Demiray, T. H. (2008). *Simulation of Power System Dynamics using Dynamic Phasor Models*. Ph.D. dissertation, ETH Zurich, Diss. No. 17607.
7. Dimo, P. (1975). *Nodal Analysis of Power Systems*. Abacus Press.
8. Dommel, H. W. (1969). Digital computer solution of electromagnetic transients in single- and multiphase networks. *IEEE Trans. Power App. Syst.*, PAS-88(4):388--399.
9. Dorfler, F. and Bullo, F. (2013). Kron reduction of graphs with applications to electrical networks. *IEEE Trans. Circuits Syst. I*, 60(1):150--163.
10. Kron, G. (1939). *Tensor Analysis of Networks*. John Wiley & Sons.
11. Kundur, P. (1994). *Power System Stability and Control*. McGraw-Hill.
12. Mattavelli, P., Stankovic, A. M., and Verghese, G. C. (1999). SSR analysis with dynamic phasor model of thyristor-controlled series capacitor. *IEEE Trans. Power Syst.*, 14(1):200--208.
13. Mirz, M., Vogel, S., Reinke, G., and Monti, A. (2019). DPsim -- a dynamic phasor real-time simulator for power systems. *SoftwareX*, 10:100253.
14. Monticelli, A., Deckmann, S., Garcia, A., and Stott, B. (1979). Real-time external equivalents for static security analysis. *IEEE Trans. Power App. Syst.*, PAS-98(2):498--508.
15. Pagola, F. L., Perez-Arriaga, I. J., and Verghese, G. C. (1989). On sensitivities, residues and participations. *IEEE Trans. Power Syst.*, 4(1):278--285.
16. Perez-Arriaga, I. J., Verghese, G. C., and Schweppe, F. C. (1982). Selective modal analysis with applications to electric power systems, Part I. *IEEE Trans. Power App. Syst.*, PAS-101(9):3117--3125.
17. Phadke, A. G. and Thorp, J. S. (2008). *Synchronized Phasor Measurements and Their Applications*. Springer.
18. Sanders, S. R., Noworolski, J. M., Liu, X. Z., and Verghese, G. C. (1991). Generalized averaging method for power conversion circuits. *IEEE Trans. Power Electron.*, 6(2):251--259.
19. Schweppe, F. C. and Wildes, J. (1970). Power system static-state estimation, Part I: exact model. *IEEE Trans. Power App. Syst.*, PAS-89(1):120--125.
20. Schweppe, F. C. and Rom, D. B. (1970). Power system static-state estimation, Part II: approximate model. *IEEE Trans. Power App. Syst.*, PAS-89(1):125--130.
21. Schweppe, F. C. (1970). Power system static-state estimation, Part III: implementation. *IEEE Trans. Power App. Syst.*, PAS-89(1):130--135.
22. Stankovic, A. M., Sanders, S. R., and Aydin, T. (2002). Dynamic phasors in modeling and analysis of unbalanced polyphase AC machines. *IEEE Trans. Energy Convers.*, 17(1):107--113.
23. Stott, B. and Alsac, O. (1974). Fast decoupled load flow. *IEEE Trans. Power App. Syst.*, PAS-93(3):859--869.
24. Tinney, W. F. and Hart, C. E. (1967). Power flow solution by Newton's method. *IEEE Trans. Power App. Syst.*, PAS-86(11):1449--1460.
25. Tinney, W. F. and Walker, J. W. (1967). Direct solutions of sparse network equations by optimally ordered triangular factorization. *Proc. IEEE*, 55(11):1801--1809.
26. Van Cutsem, T. and Vournas, C. (1998). *Voltage Stability of Electric Power Systems*. Springer.
27. Ward, J. B. (1949). Equivalent circuits for power flow studies. *AIEE Trans. Power App. Syst.*, 68(1):373--382.
