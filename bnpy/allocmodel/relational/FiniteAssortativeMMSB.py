'''
FiniteAssortativeMMSB.py

Assortative mixed membership stochastic blockmodel.
'''
import numpy as np
import itertools

from bnpy.allocmodel import AllocModel
from bnpy.suffstats import SuffStatBag
from bnpy.util import gammaln, digamma, EPS
from bnpy.util.NumericUtil import calcRlogR
from relational.FiniteMMSB import FiniteMMSB


class FiniteAssortativeMMSB(FiniteMMSB):

    """ Assortative version of FiniteMMSB. Finite number of components K.

    Attributes
    -------
    * inferType : string {'EM', 'VB', 'moVB', 'soVB'}
        indicates which updates to perform for local/global steps
    * K : int
        number of components
    * alpha : float
        scalar symmetric Dirichlet prior on mixture weights

    Attributes for VB
    ---------
    * theta : 1D array, size K
        Estimated parameters for Dirichlet posterior over mix weights
        theta[k] > 0 for all k
    """

    def __init__(self, inferType, priorDict=dict()):
        super(FiniteAssortativeMMSB, self).__init__(inferType, priorDict)

    def set_prior(self, alpha=0.1, epsilon=0.05):
        self.alpha = alpha
        self.epsilon = epsilon

    def getCompDims(self):
        ''' Get dimensions of latent component interactions.

        Assortative models use only K states.

        Returns
        -------
        dims : tuple
        '''
        return ('K',)

    def E_logPi(self):
        ''' Compute expected probability \pi for each node and state

        Returns
        -------
        ElogPi : nNodes x K
        '''
        ElogPi = digamma(self.theta) - \
            digamma(np.sum(self.theta, axis=1))[:, np.newaxis]
        return ElogPi        

    def calc_local_params(self, Data, LP, **kwargs):
        ''' Compute local parameters for provided dataset.

        Args
        -------
        Data : GraphData object
        LP : dict of local params, with fields
            * E_log_soft_ev : nEdges x K
        
        Returns
        -------
        LP : dict of local params, with fields
            * resp : nEdges x K
                resp[e,k] = prob that edge e is explained by 
                connection from state/block combination k,k
        '''
        K = self.K
        ElogPi = self.E_logPi()

        # epsEvVec : 1D array, size nEdges
        #    holds the likelihood that edge was generated by bg state "epsilon"
        logepsEvVec = np.sum(
            np.log(self.epsilon) * Data.X + \
            np.log(1-self.epsilon) * (1-Data.X),
            axis=1)
        epsEvVec = np.exp(logepsEvVec)

        # resp : 2D array, nEdges x K
        resp = ElogPi[Data.edges[:,0], :] + \
            ElogPi[Data.edges[:,1], :] + \
            LP['E_log_soft_ev']
        np.exp(resp, out=resp)

        expElogPi = np.exp(ElogPi)

        # sumPi_fg : 1D array, size nEdges
        #    sumPi_fg[e] = \sum_k \pi[s,k] \pi[t,k] for edge e=(s,t)
        sumPi_fg = np.sum(
            expElogPi[Data.edges[:,0]] * expElogPi[Data.edges[:,1]],
            axis=1)
        # sumPi : 1D array, size nEdges
        #    sumPi[e] = \sum_j,k \pi[s,j] \pi[t,k] for edge e=(s,t)
        sumexpElogPi = expElogPi.sum(axis=1)
        sumPi = sumexpElogPi[Data.edges[:,0]] * \
            sumexpElogPi[Data.edges[:,1]]

        # respNormConst : 1D array, size nEdges
        respNormConst = resp.sum(axis=1)
        respNormConst += (sumPi - sumPi_fg) * epsEvVec
        # Normalize the rows of resp
        resp /= respNormConst[:,np.newaxis]
        np.maximum(resp, 1e-100, out=resp)
        LP['resp'] = resp

        # Compute resp_bg : 1D array, size nEdges
        resp_bg = 1.0 - resp.sum(axis=1)
        LP['resp_bg'] = resp_bg

        # src/rcv resp_bg : 2D array, size nEdges x K
        #     srcresp_bg[n,k] = sum of resp mass 
        #         when edge n's src asgned to k, but rcv is not
        #     rcvresp_bg[n,k] = sum of resp mass 
        #         when edge n's rcv asgned to k, but src is not
        epsEvVec /= respNormConst
        expElogPi_bg = sumexpElogPi[:,np.newaxis] - expElogPi
        srcresp_bg = epsEvVec[:,np.newaxis] * \
                expElogPi[Data.edges[:,0]] * \
                expElogPi_bg[Data.edges[:,1]]
        rcvresp_bg = epsEvVec[:,np.newaxis] * \
                expElogPi[Data.edges[:,1]] * \
                expElogPi_bg[Data.edges[:,0]]
        # NodeStateCount_bg : 2D array, size nNodes x K
        #     NodeStateCount_bg[v,k] = count of node v asgned to state k
        #         when other node in edge is NOT assigned to state k
        NodeStateCount_bg = \
            Data.getSparseSrcNodeMat() * srcresp_bg + \
            Data.getSparseRcvNodeMat() * rcvresp_bg
        # NodeStateCount_fg : 2D array, size nNodes x K
        nodeMat = Data.getSparseSrcNodeMat() + Data.getSparseRcvNodeMat()
        NodeStateCount_fg = nodeMat * LP['resp']
        LP['NodeStateCount'] = NodeStateCount_bg + NodeStateCount_fg
        LP['N_fg'] = NodeStateCount_fg.sum(axis=0)

        # Ldata_bg : scalar
        #     cached value of ELBO term Ldata for background component
        LP['Ldata_bg'] = np.inner(resp_bg, logepsEvVec)

        LP['Lentropy_fg'] = -1 * calcRlogR(LP['resp'])

        Lentropy_fg = \
            -1 * np.sum(NodeStateCount_fg * ElogPi, axis=0) + \
            -1 * np.sum(LP['resp'] * LP['E_log_soft_ev'], axis=0) + \
            np.dot(np.log(respNormConst), LP['resp'])
        assert np.allclose(Lentropy_fg, LP['Lentropy_fg'])
        """
        LP['Lentropy_normConst'] = np.sum(np.log(respNormConst))
        LP['Lentropy_lik_fg'] = -1 * np.sum(
            LP['resp']*LP['E_log_soft_ev'], axis=0)
        LP['Lentropy_prior'] = -1 * np.sum(
            LP['NodeStateCount'] * ElogPi, axis=0)
        LP['Lentropy_lik_bg'] = -1 * LP['Ldata_bg']
        """
        # Lentropy_bg : scalar
        #     Cached value of entropy of all background resp values
        #     Equal to \sum_n \sum_{j\neq k} r_{njk} \log r_{njk}
        #     This is strictly lower-bounded (but NOT equal to)
        #      -1 * calcRlogR(LP['resp_bg'])
        LP['Lentropy_bg'] = \
            -1 * np.sum(NodeStateCount_bg * ElogPi) + \
            -1 * LP['Ldata_bg'] + \
            np.inner(np.log(respNormConst), LP['resp_bg'])            
        return LP


    def initLPFromResp(self, Data, LP):
        ''' Initialize local parameters given LP dict with resp field.
        '''
        K = LP['resp'].shape[-1]
        nodeMat = Data.getSparseSrcNodeMat() + Data.getSparseRcvNodeMat()

        if LP['resp'].ndim == 2:
            # Assortative block relations
            resp = LP['resp']
            resp_bg = LP['resp_bg']
            assert resp_bg.shape == (Data.nEdges,)
            NodeStateCount_bg = 0.0

        else:
            # Full K x K block relations
            resp = np.zeros((Data.nEdges, K))
            for k in xrange(K):
                resp[:,k] = LP['resp'][:, k, k]
            srcresp_bg = LP['resp'].sum(axis=2) - resp
            rcvresp_bg = LP['resp'].sum(axis=1) - resp
            NodeStateCount_bg = \
                Data.getSparseSrcNodeMat() * srcresp_bg + \
                Data.getSparseRcvNodeMat() * rcvresp_bg
        LP['resp'] = resp

        # NodeStateCount_fg : 2D array, size nNodes x K
        NodeStateCount_fg = nodeMat * LP['resp']
        LP['NodeStateCount'] = NodeStateCount_bg + NodeStateCount_fg
        LP['N_fg'] = NodeStateCount_fg.sum(axis=0)
        return LP


    def get_global_suff_stats(self, Data, LP, doPrecompEntropy=0, **kwargs):
        ''' Compute sufficient stats for provided dataset and local params

        Returns
        -------
        SS : SuffStatBag with K components and fields
            * sumSource : nNodes x K
            * sumReceiver : nNodes x K
        '''
        V = Data.nNodes
        K = LP['resp'].shape[-1]
        SS = SuffStatBag(K=K, D=Data.dim, V=V)
        if 'NodeStateCount' not in LP:
            assert 'resp' in LP
            LP = self.initLPFromResp(Data, LP)
        SS.setField('NodeStateCount', LP['NodeStateCount'], dims=('V', 'K'))
        if np.allclose(LP['resp'].sum(axis=1).min(), 1.0):
            # If the LP fully represents all present edges,
            # then the NodeStateCount should as well.
            assert np.allclose(SS.NodeStateCount, Data.nEdges * 2)
        SS.setField('N', LP['N_fg'], dims=('K',))
        SS.setField('scaleFactor', Data.nEdges, dims=None)

        if 'Ldata_bg' in LP:
            SS.setELBOTerm('Ldata_bg', LP['Ldata_bg'], dims=None)

        if doPrecompEntropy:
            Hresp_fg = LP['Lentropy_fg'] # = -1 * calcRlogR(LP['resp'])
            Hresp_bg = LP['Lentropy_bg']
                        
            SS.setELBOTerm('Hresp', Hresp_fg, dims='K')
            SS.setELBOTerm('Hresp_bg', Hresp_bg, dims=None)
            
            
        return SS

 
    def calc_evidence(self, Data, SS, LP, todict=0, **kwargs):
        ''' Compute training objective function on provided input.

        Returns
        -------
        L : scalar float
        '''
        Lalloc = self.L_alloc_no_slack()
        Lslack = self.L_slack(SS)
        # Compute entropy term
        if SS.hasELBOTerm('Hresp'):
            Lentropy = SS.getELBOTerm('Hresp').sum() + \
                SS.getELBOTerm('Hresp_bg')
        else:
            Lentropy = self.L_entropy(LP)

        if SS.hasELBOTerm('Ldata_bg'):
            Lbgdata = SS.getELBOTerm('Ldata_bg')
        else:
            Lbgdata = LP['Ldata_bg']
        if todict:
            return dict(Lentropy=Lentropy, 
                Lalloc=Lalloc, Lslack=Lslack,
                Lbgdata=Lbgdata)
        return Lalloc + Lentropy + Lslack + Lbgdata

    def L_entropy(self, LP):
        ''' Compute entropy term of objective as scalar

        Returns
        -------
        Lentropy : scalar
            = foreground + background entropy values
        '''
        assert 'Lentropy_bg' in LP
        return LP['Lentropy_fg'].sum() + LP['Lentropy_bg']

    def _calc_local_params_Naive(self, Data, LP, **kwargs):
        ''' Compute local parameters for provided dataset.

        Uses naive representation with N x K x K memory cost for resp

        Args
        -------
        Data : GraphData object
        LP : dict of local params, with fields
            * E_log_soft_ev : nEdges x K
        
        Returns
        -------
        LP : dict
            Local parameters
        '''
        K = self.K
        ElogPi = digamma(self.theta) - \
            digamma(np.sum(self.theta, axis=1))[:, np.newaxis]

        # resp : nEdges x K x K
        #    resp[e(s,t),k,l] = ElogPi[s,k] + ElogPi[t,l] + likelihood
        resp = ElogPi[Data.edges[:,0], :, np.newaxis] + \
               ElogPi[Data.edges[:,1], np.newaxis, :]

        if Data.isSparse:  # Sparse binary data.
            raise NotImplementedError("TODO")

        logSoftEv = LP['E_log_soft_ev']  # E x K x K
        for k in xrange(K):
            resp[:, k, k] += logSoftEv[:, k]

        logepsEvVec = np.sum(
            np.log(self.epsilon) * Data.X + \
            np.log(1-self.epsilon) * (1-Data.X),
            axis=1)
        for j, k in itertools.product(xrange(K), xrange(K)):
            if j == k:
                continue
            resp[:, j, k] += logepsEvVec

        # In-place exp and normalize
        #resp -= np.max(resp, axis=(1,2))[:, np.newaxis, np.newaxis]
        np.exp(resp, out=resp)
        respNormConst = resp.sum(axis=(1,2))[:, np.newaxis, np.newaxis]

        respNormConst_fg = np.zeros(Data.nEdges)
        for k in xrange(K):
            respNormConst_fg += resp[:, k, k]


        resp /= respNormConst
        LP['resp'] = resp
        LP['respNormConst'] = respNormConst
        LP['respNormConst_fg'] = respNormConst_fg

        NodeStateCount_fg = np.zeros((Data.nNodes, K))
        for k in xrange(K):
            NodeStateCount_fg[:,k] += \
                Data.getSparseSrcNodeMat() * resp[:, k, k]
            NodeStateCount_fg[:,k] += \
                Data.getSparseRcvNodeMat() * resp[:, k, k]

        NodeStateCount_bg = np.zeros((Data.nNodes, K))
        for k in xrange(K):
            srcResp =  resp[:, k, :k].sum(axis=1) + \
                resp[:, k, k+1:].sum(axis=1)
            rcvResp =  resp[:, :k, k].sum(axis=1) + \
                resp[:, k+1:, k].sum(axis=1)

            NodeStateCount_bg[:,k] += \
                Data.getSparseSrcNodeMat() * srcResp
            NodeStateCount_bg[:,k] += \
                Data.getSparseRcvNodeMat() * rcvResp
        LP['NodeStateCount_bg'] = NodeStateCount_bg
        LP['NodeStateCount_fg'] = NodeStateCount_fg
        return LP

    def to_dict(self):
        return dict(theta=self.theta)

    def from_dict(self, myDict):
        self.inferType = myDict['inferType']
        self.K = myDict['K']
        self.theta = myDict['theta']

    def get_prior_dict(self):
        return dict(alpha=self.alpha, epsilon=self.epsilon)

