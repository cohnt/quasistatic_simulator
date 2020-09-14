
from pydrake.common.value import AbstractValue
from pydrake.systems.meshcat_visualizer import (
    MeshcatVisualizer, MeshcatContactVisualizer)
from pydrake.systems.framework import DiagramBuilder, LeafSystem
from pydrake.multibody.tree import JacobianWrtVariable
from pydrake.solvers import mathematicalprogram as mp
from pydrake.solvers.gurobi import GurobiSolver

from setup_environments import *
from contact_aware_control.contact_particle_filter.utils_cython import (
    CalcTangentVectors)
from problem_definition_pinch import CalcE


#%%
class QuasistaticSimulator:
    def __init__(self, setup_environment, nd_per_contact):
        """
        Let's assume that
        - There's only one unactuated and one actuated model instance.
        - Each rigid body has one contact geometry.
        """
        # Construct diagram system for proximity queries, Jacobians.
        builder = DiagramBuilder()
        plant, scene_graph, robot_model, object_model = setup_environment(
            builder)
        viz = MeshcatVisualizer(
            scene_graph, frames_to_draw={"three_link_arm": {"link_ee"}})
        builder.AddSystem(viz)
        builder.Connect(
            scene_graph.get_pose_bundle_output_port(),
            viz.GetInputPort("lcm_visualization"))
        diagram = builder.Build()
        viz.load()

        self.diagram = diagram
        self.plant = plant
        self.scene_graph = scene_graph
        self.viz = viz
        self.inspector = scene_graph.model_inspector()

        self.context = diagram.CreateDefaultContext()
        self.context_plant = diagram.GetMutableSubsystemContext(
            plant, self.context)
        self.context_sg = diagram.GetMutableSubsystemContext(
            scene_graph, self.context)
        self.context_meshcat = diagram.GetMutableSubsystemContext(
            self.viz, self.context)

        # Get actuated and un-actuated model instances in respective lists?
        self.models_actuated = [robot_model]
        self.models_unactuated = [object_model]
        self.body_indices_actuated = []
        self.body_indices_unactuated = []
        self.position_indices_actuated = []
        self.position_indices_unactuated = []

        for model_a in self.models_actuated:
            self.body_indices_actuated.append(plant.GetBodyIndices(model_a))
            self.position_indices_actuated.append(
                self.GetPositionsIndicesForModel(model_a))

        for model_u in self.models_unactuated:
            self.body_indices_unactuated.append(plant.GetBodyIndices(model_u))
            self.position_indices_unactuated.append(
                self.GetPositionsIndicesForModel(model_u))

        # compute n_u and n_a
        self.n_a_list = np.array(
            [plant.num_positions(model) for model in self.models_actuated],
            dtype=np.int)
        self.n_a = self.n_a_list.sum()
        self.n_u_list = np.array(
            [plant.num_positions(model) for model in self.models_unactuated],
            dtype=np.int)
        self.n_u = self.n_u_list.sum()

        self.nd_per_contact = nd_per_contact

        # solver
        self.solver = GurobiSolver()
        assert self.solver.available()

    def UpdateConfiguration(self, q):
        """
        :param q = [q_u, q_a]
        :return:
        """
        # Update state in plant_context
        q_u = q[:self.n_u]
        q_a = q[self.n_u:]
        assert len(self.models_actuated) <= 1
        assert len(self.models_unactuated) <= 1
        for model_a in self.models_actuated:
            self.plant.SetPositions(
                self.context_plant, model_a, q_a)
        for model_u in self.models_unactuated:
            self.plant.SetPositions(
                self.context_plant, model_u, q_u)

    def DrawCurrentConfiguration(self):
        self.viz.DoPublish(self.context_meshcat, [])

    def UpdateNormalAndTangentialJacobianRows(
            self, body, pC_D, n_W, i_c: int, n_di: int, i_f_start: int,
            position_indices, Jn, Jf):
        """
        Updates corresonding rows of Jn and Jf.
        :param body: a RigidBody object that belongs to either
            self.body_indices_actuated or self.body_indices_unactuated.
            D is the body frame of body.
        :param pC_D: contact point in frame D.
        :param n_W: contact normal pointing into body, expressed in W.
        :param i_C: contact index, the index of the row of Jn to be modified.
        :param n_di: number of tangent vectors spanning the tangent plane.
        :param i_f_start: starting row Jf to be modified.
        :param position_indices: columns of J_q corresponding to the model
            instance to which body belongs.
        :param Jn: normal jacobian of shape(n_c, len(position_indices)).
        :param Jf: tangent jacobian of shape(n_f, len(position_indices)).
        :return: None.
        """
        J_q_WBi = self.plant.CalcJacobianTranslationalVelocity(
            context=self.context_plant,
            with_respect_to=JacobianWrtVariable.kQDot,
            frame_B=body.body_frame(),
            p_BoBi_B=pC_D,
            frame_A=self.plant.world_frame(),
            frame_E=self.plant.world_frame())
        J_qa_WBi = J_q_WBi[:, position_indices]
        dC = CalcTangentVectors(n_W, n_di)

        Jn[i_c] = n_W.dot(J_qa_WBi)
        Jf[i_f_start: i_f_start + n_di] = dC.dot(J_qa_WBi)

    @staticmethod
    def FindContactFromSignedDistancePair(bodyA, bodyB, sdp, body_indices):
        """
        Determine if either of the two bodies (bodyA and bodyB) are in
        body_indices_list. If true, return
            - the body in body_indices_list.
            - the contact point in the body's frame.
            - the contact normal pointing into the body.
        An exception is thrown if both bodyA and bodyB are in body_indices.

        :param bodyA: A RigidBody object containing geometry id_A in sdp.
        :param bodyB: A RigidBody object containing geometry id_B in sdp.
        :param sdp: A SignedDistancePair object.
        :param body_indices: A list/set of body indices.
        :return:
        """
        # D: frame of body
        # pC_D: "contact" point for the body expressed in frame D.
        # n_W: contact normal pointing away from the body expressed in world frame.

        body_D, pC_D, n_W = None, None, None
        is_A_in = bodyA.index() in body_indices
        is_B_in = bodyB.index() in body_indices

        if is_A_in and is_B_in:
            raise RuntimeError("Self collision cannot be handled yet.")

        if is_A_in:
            body_D = bodyA
            pC_D = sdp.p_ACa
            n_W = sdp.nhat_BA_W
        elif is_B_in:
            body_D = bodyB
            pC_D = sdp.p_BCb
            n_W = -sdp.nhat_BA_W

        return body_D, pC_D, n_W

    def CalcContactJacobians(self, contact_detection_tolerance):
        """
        For all contact detected by scene graph, computes Jn and Jf.
        q = [q_u, q_a]
        :param q:
        :return:
        """
        # Evaluate contacts.
        query_object = self.scene_graph.get_query_output_port().Eval(
            self.context_sg)
        signed_distance_pairs = \
            query_object.ComputeSignedDistancePairwiseClosestPoints(
                contact_detection_tolerance)

        n_c = len(signed_distance_pairs)
        n_d = np.full(n_c, self.nd_per_contact)
        n_f = n_d.sum()

        phi = np.zeros(n_c)
        Jn_u = np.zeros((n_c, self.n_u))
        Jn_a = np.zeros((n_c, self.n_a))
        Jf_u = np.zeros((n_f, self.n_u))
        Jf_a = np.zeros((n_f, self.n_a))

        i_f_start = 0
        for i_c, sdp in enumerate(signed_distance_pairs):
            phi[i_c] = sdp.distance
            body1 = self.GetMbpBodyFromSceneGraphGeometry(sdp.id_A)
            body2 = self.GetMbpBodyFromSceneGraphGeometry(sdp.id_B)

            # A: frame of actuated body.
            # U: frame of unactuated body.
            # body_a: actuated body
            # pCa_A: "contact" point for the actuated body expressed in frame A.
            # n_a_W: contact normal pointing away from the actuated body
            #   expressed in world frame.

            body_a, pCa_A, n_a_W = self.FindContactFromSignedDistancePair(
                body1, body2, sdp, self.body_indices_actuated[0])

            body_u, pCu_U, n_u_W = self.FindContactFromSignedDistancePair(
                body1, body2, sdp, self.body_indices_unactuated[0])

            if body_a is not None:
                self.UpdateNormalAndTangentialJacobianRows(
                    body=body_a, pC_D=pCa_A, n_W=n_a_W, i_c=i_c, n_di=n_d[i_c],
                    i_f_start=i_f_start,
                    position_indices=self.position_indices_actuated[0],
                    Jn=Jn_a, Jf=Jf_a)

            if body_u is not None:
                self.UpdateNormalAndTangentialJacobianRows(
                    body=body_u, pC_D=pCu_U, n_W=n_u_W, i_c=i_c, n_di=n_d[i_c],
                    i_f_start=i_f_start,
                    position_indices=self.position_indices_unactuated[0],
                    Jn=Jn_u, Jf=Jf_u)

            i_f_start += n_d[i_c]

        return n_c, n_d, n_f, Jn_u, Jn_a, Jf_u, Jf_a, phi

    def GetMbpBodyFromSceneGraphGeometry(self, g_id):
        f_id = self.inspector.GetFrameId(g_id)
        return self.plant.GetBodyFromFrameId(f_id)

    def GetPositionsIndicesForModel(self, model_instance_index):
        selector = np.arange(self.plant.num_positions())
        return self.plant.GetPositionsFromArray(
            model_instance_index, selector).astype(np.int)

    # TODO: P_ext and h should probably come from elsewhere...
    def StepAnitescu(self, q, q_a_cmd, tau_u_ext, h):
        self.UpdateConfiguration(q)
        n_c, n_d, n_f, Jn_u, Jn_a, Jf_u, Jf_a, phi_l = \
            self.CalcContactJacobians(0.1)
        dq_a_cmd = q_a_cmd - q[self.n_u:]

        prog = mp.MathematicalProgram()
        dq_u = prog.NewContinuousVariables(self.n_u, "dq_u")
        dq_a = prog.NewContinuousVariables(self.n_a, "dq_a")

        # TODO: don't hard code these.
        Kq_a = np.eye(self.n_a) * 1000
        P_ext = tau_u_ext * h
        U = np.eye(n_c) * 0.8

        prog.AddQuadraticCost(Kq_a * h, -Kq_a.dot(dq_a_cmd) * h, dq_a)
        prog.AddLinearCost(-P_ext, 0, dq_u)

        Jn = np.hstack([Jn_u, Jn_a])
        Jf = np.hstack([Jf_u, Jf_a])
        J = np.zeros_like(Jf)
        phi_constraints = np.zeros(n_f)

        j_start = 0
        for i in range(n_c):
            for j in range(n_d[i]):
                idx = j_start + j
                J[idx] = Jn[i] + U[i, i] * Jf[idx]
                phi_constraints[idx] = phi_l[i]
            j_start += n_d[i]

        dq = np.hstack([dq_u, dq_a])
        constraints = prog.AddLinearConstraint(
            J, -phi_constraints, np.full_like(phi_constraints, np.inf), dq)

        result = self.solver.Solve(prog, None, None)
        beta = result.GetDualSolution(constraints)
        beta = np.array(beta).squeeze()
        dq_a = result.GetSolution(dq_a)
        dq_u = result.GetSolution(dq_u)
        constraint_values = phi_constraints + result.EvalBinding(constraints)

        return dq_a, dq_u, beta, constraint_values, result