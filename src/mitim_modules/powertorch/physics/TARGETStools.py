import torch
from mitim_tools.misc_tools import PLASMAtools
from mitim_tools.misc_tools.IOtools import printMsg as print
from IPython import embed

# ------------------------------------------------------------------
# Main classes
# ------------------------------------------------------------------

class power_targets:
    '''
    Default class for power target models, change "evaluate" method to implement a new model
    '''

    def evaluate(self):
        print("No model implemented for power targets", typeMsg="w")

    def __init__(self,powerstate):
        self.powerstate = powerstate

        # Make sub-targets equal to zero
        variables_to_zero = ["qfuse", "qfusi", "qie", "qrad", "qrad_bremms", "qrad_line", "qrad_sync"]
        for i in variables_to_zero:
            self.powerstate.plasma[i] = self.powerstate.plasma["te"] * 0.0

        # ----------------------------------------------------
        # Fixed Targets (targets without a model)
        # ----------------------------------------------------

        if self.powerstate.TargetOptions['ModelOptions']['TypeTarget'] == 1:
            self.PextraE, self.PextraI = (
                self.powerstate.plasma["PextraE_Target1"],
                self.powerstate.plasma["PextraI_Target1"],
            )  # Original integrated from input.gacode
        elif self.powerstate.TargetOptions['ModelOptions']['TypeTarget'] == 2:
            self.PextraE, self.PextraI = (
                self.powerstate.plasma["PextraE_Target2"],
                self.powerstate.plasma["PextraI_Target2"],
            )
        elif self.powerstate.TargetOptions['ModelOptions']['TypeTarget'] == 3:
            self.PextraE, self.PextraI = self.powerstate.plasma["te"] * 0.0, self.powerstate.plasma["te"] * 0.0

        # For the moment, I don't have a model for these, so I just grab the original from input.gacode
        self.CextraE = self.powerstate.plasma["Gaux_e"]     # 1E20/s/m^2
        self.CextraZ = self.powerstate.plasma["Gaux_Z"]     # 1E20/s/m^2
        self.Mextra = self.powerstate.plasma["Maux"]        # J/m^2

    def fine_grid(self):

        """
        Make all quantities needed on the fine resolution
        -------------------------------------------------
            In the powerstate creation, the plasma variables are stored in two different resolutions, one for the coarse grid and one for the fine grid,
            if the option is activated.

            Here, at calculation stage I use some precalculated quantities in the fine grid and then integrate the gradients into that resolution

            Note that the set ['te','ti','ne','nZ','w0','ni'] will automatically be substituted during the update_var() that comes next, so
            it's ok that I lose the torch leaf here. However, I must do this copy here because if any of those variables are not updated in
            update_var() then it would fail. But first store them for later use.
        """

        self.plasma_original = {}

        # Bring to fine grid
        variables_to_fine = ["B_unit", "B_ref", "volp", "rmin", "roa", "rho", "ni"]
        for variable in variables_to_fine:
            self.plasma_original[variable] = self.powerstate.plasma[variable].clone()
            self.powerstate.plasma[variable] = self.powerstate.plasma_fine[variable]

        # Bring also the gradients and kinetic variables
        for variable in self.powerstate.profile_map.keys():

            # Kinetic variables (te,ti,ne,nZ,w0,ni)
            self.plasma_original[variable] = self.powerstate.plasma[variable].clone()
            self.powerstate.plasma[variable] = self.powerstate.plasma_fine[variable]

            # Bring also the gradients that are part of the torch trees, so that the derivative is not lost
            self.plasma_original[f'aL{variable}'] = self.powerstate.plasma[f'aL{variable}'].clone()

        # ----------------------------------------------------
        # Integrate through fine de-parameterization
        # ----------------------------------------------------
        for i in self.powerstate.ProfilesPredicted:
            _ = self.powerstate.update_var(
                i,
                specific_deparametrizer=self.powerstate.deparametrizers_coarse_middle,
            )

    def flux_integrate(self):
        """
		**************************************************************************************************
		Calculate integral of all targets, and then sum aux.
		Reason why I do it this convoluted way is to make it faster in mitim, not to run integrateQuadPoly all the time.
		Run once for all the batch and also for electrons and ions
		(in MW/m^2)
		**************************************************************************************************
		"""

        qe = self.powerstate.plasma["te"]*0.0
        qi = self.powerstate.plasma["te"]*0.0
        
        if self.powerstate.TargetOptions['ModelOptions']['TypeTarget'] >= 2:
            qe += -self.powerstate.plasma["qie"]
            qi +=  self.powerstate.plasma["qie"]
        
        if self.powerstate.TargetOptions['ModelOptions']['TypeTarget'] == 3:
            qe +=  self.powerstate.plasma["qfuse"] - self.powerstate.plasma["qrad"]
            qi +=  self.powerstate.plasma["qfusi"]

        q = torch.cat((qe, qi)).to(qe)
        self.P = self.powerstate.volume_integrate(q, force_dim=q.shape[0])

    def coarse_grid(self):

        # **************************************************************************************************
        # Come back to original grid for targets
        # **************************************************************************************************

        # Interpolate results from fine to coarse (i.e. whole point is that it is better than integrate interpolated values)
        if self.powerstate.TargetOptions['ModelOptions']['TypeTarget'] >= 2:
            for i in ["qie"]:
                self.powerstate.plasma[i] = self.powerstate.plasma[i][:, self.powerstate.positions_targets]
        
        if self.powerstate.TargetOptions['ModelOptions']['TypeTarget'] == 3:
            for i in [
                "qfuse",
                "qfusi",
                "qrad",
                "qrad_bremms",
                "qrad_line",
                "qrad_sync",
            ]:
                self.powerstate.plasma[i] = self.powerstate.plasma[i][:, self.powerstate.positions_targets]
       
        self.P = self.P[:, self.powerstate.positions_targets]

        # Recover variables calculated prior to the fine-targets method
        for i in self.plasma_original:
            self.powerstate.plasma[i] = self.plasma_original[i]

    def postprocessing(self, useConvectiveFluxes=False, forceZeroParticleFlux=False, assumedPercentError=1.0):

        # **************************************************************************************************
        # Plug-in Targets
        # **************************************************************************************************

        self.powerstate.plasma["Pe"] = (
            self.powerstate.plasma["Paux_e"] + self.P[: self.P.shape[0]//2, :] + self.PextraE
        )  # MW/m^2
        self.powerstate.plasma["Pi"] = (
            self.powerstate.plasma["Paux_i"] + self.P[self.P.shape[0]//2 :, :] + self.PextraI
        )  # MW/m^2
        self.powerstate.plasma["Ce_raw"] = self.CextraE
        self.powerstate.plasma["CZ_raw"] = self.CextraZ
        self.powerstate.plasma["Mt"] = self.Mextra

        # Merge convective fluxes

        if useConvectiveFluxes:
            self.powerstate.plasma["Ce"] = PLASMAtools.convective_flux(
                self.powerstate.plasma["te"], self.powerstate.plasma["Ce_raw"]
            )  # MW/m^2
            self.powerstate.plasma["CZ"] = PLASMAtools.convective_flux(
                self.powerstate.plasma["te"], self.powerstate.plasma["CZ_raw"]
            )  # MW/m^2
        else:
            self.powerstate.plasma["Ce"] = self.powerstate.plasma["Ce_raw"]
            self.powerstate.plasma["CZ"] = self.powerstate.plasma["CZ_raw"]

        if forceZeroParticleFlux:
            self.powerstate.plasma["Ce"] = self.powerstate.plasma["Ce"] * 0
            self.powerstate.plasma["Ce_raw"] = self.powerstate.plasma["Ce_raw"] * 0

        # **************************************************************************************************
        # Error
        # **************************************************************************************************

        variables_to_error = ["Pe", "Pi", "Ce", "CZ", "Mt", "Ce_raw", "CZ_raw"]

        for i in variables_to_error:
            self.powerstate.plasma[i + "_stds"] = self.powerstate.plasma[i] * assumedPercentError / 100 

        """
		**************************************************************************************************
		GB Normalized
		**************************************************************************************************
			Note: This is useful for mitim surrogate variables of targets
		"""

        gb_mapping = {
            "Pe": "Qgb",
            "Pi": "Qgb",
            "Ce": "Qgb" if useConvectiveFluxes else "Ggb",
            "CZ": "Qgb" if useConvectiveFluxes else "Ggb",
            "Mt": "Pgb",
        }

        for i in gb_mapping.keys():
            self.powerstate.plasma[f"{i}GB"] = self.powerstate.plasma[i] / self.powerstate.plasma[gb_mapping[i]]

# ----------------------------------------------------------------------------------------------------
# Full analytical models taken from TGYRO
# ----------------------------------------------------------------------------------------------------

# Global physical constants

u = 1.66054e-24  # g
Ae = 9.1094e-28 / u  # Electron mass in atomic units # 9.1094E-28/u
Aalpha = 2 * (3.34358e-24) / u  # Alpha mass in atomic units
Ealpha = 3.5e6  # eV
e = 1.60218e-19
pi = 3.14159265

# For Bosh XS
c1, c2, c3 = 1.17302e-9, 1.51361e-2, 7.51886e-2
c4, c5, c6, c7 = 4.60643e-3, 1.3500e-2, -1.06750e-4, 1.36600e-5
bg, er = 34.3827, 1.124656e6

class analytical_model(power_targets):
    def __init__(self,powerstate, **kwargs):
        super().__init__(powerstate, **kwargs)

    def evaluate(self):

        if self.powerstate.TargetOptions["ModelOptions"]["TypeTarget"] >= 2:
            self._evaluate_energy_exchange()

        if self.powerstate.TargetOptions["ModelOptions"]["TypeTarget"] == 3:
            self._evaluate_alpha_heating()
            self._evaluate_radiation()

    def _evaluate_energy_exchange(self):
        '''
        ----------------------------------------------------
        Classical energy exchange
        ----------------------------------------------------
        '''

        self.powerstate.plasma["qie"] = PLASMAtools.energy_exchange(
            self.powerstate.plasma["te"],
            self.powerstate.plasma["ti"],
            self.powerstate.plasma["ne"] * 1e-1,
            self.powerstate.plasma["ni"] * 1e-1,
            self.powerstate.plasma["ions_set_mi"],
            self.powerstate.plasma["ions_set_Zi"],
        )

    def _evaluate_alpha_heating(self):
        '''
        ----------------------------------------------------
        Alpha heating
        ----------------------------------------------------

        This script calculates the power density profile (W/cm^3) that goes to ions and to electrons from
        fusion alphas, using kinetic profiles as inputs.

        This method follows the same methodology as in TGYRO [Candy et al. PoP 2009] and all the credits
        are due to the authors of TGYRO. From the source code, this function follows the same procedures
        as in tgyro_auxiliary_routines.f90.

        '''

        # -----------------------------------------------------------
        # Obtain the Deuterium and Tritium densities,
        # otherwise there is no alpha power and zeros are returned
        # -----------------------------------------------------------

        if (not self.powerstate.plasma["ions_set_Dion"][0].isnan()) and (not self.powerstate.plasma["ions_set_Tion"][0].isnan()):
            n_d = self.powerstate.plasma["ni"][..., self.powerstate.plasma["ions_set_Dion"][0]] * 1e19
            n_t = self.powerstate.plasma["ni"][..., self.powerstate.plasma["ions_set_Tion"][0]] * 1e19  # m^-3
        else:
            self.powerstate.plasma["qfusi"] = self.powerstate.plasma["te"] * 0.0
            self.powerstate.plasma["qfuse"] = self.powerstate.plasma["te"] * 0.0
            return

        # -----------------------------------------------------------
        # Alpha energy birth rate
        # -----------------------------------------------------------

        sigv = sigv_fun(self.powerstate.plasma["ti"])
        s_alpha_he = sigv * (n_d * 1e-6) * (n_t * 1e-6)  # Reactions/cm^3/s
        p_alpha_he = s_alpha_he * Ealpha * e  # W/cm^3

        # -----------------------------------------------------------
        # Partition between electrons and ions
        # 	from [Stix, Plasma Phys. 14 (1972) 367], Eqs. 15 and 17
        # -----------------------------------------------------------

        c_a = self.powerstate.plasma["te"] * 0.0
        for i in range(self.powerstate.plasma["ni"].shape[2]):
            c_a += (self.powerstate.plasma["ni"][..., i] / self.powerstate.plasma["ne"]) * self.powerstate.plasma["ions_set_Zi"][:,i].unsqueeze(-1) ** 2 * (Aalpha / self.powerstate.plasma["ions_set_mi"][:,i].unsqueeze(-1))

        W_crit = (self.powerstate.plasma["te"] * 1e3) * (4 * (Ae / Aalpha) ** 0.5 / (3 * pi**0.5 * c_a)) ** (
            -2.0 / 3.0
        )  # in eV

        frac_ai = sivukhin(Ealpha / W_crit)  # This solves Eq 17 of Stix

        # -----------------------------------------------------------
        # Return power density profile
        # -----------------------------------------------------------
        self.powerstate.plasma["qfusi"] = p_alpha_he * frac_ai
        self.powerstate.plasma["qfuse"] = p_alpha_he * (1 - frac_ai)

    def _evaluate_radiation(self):

        """
        ----------------------------------------------------
        Radiation
        ----------------------------------------------------

        This script calculates the radiated power density profile (W/cm^3) from synchrotron,
        Bremsstralung and line radiation.
        Note that the ADAS data embeded in the Chebyshev polynomial coefficients already includes
        Bremsstralung and therefore to separate in between the two, it must be estimated somehow else.

        It follows the methodology in TGYRO [Candy et al. PoP 2009]. All the credits are due to
        the authors of TGYRO
        """

        Te_keV = self.powerstate.plasma["te"]
        ne20 = self.powerstate.plasma["ne"] * 1e-1
        b_ref = self.powerstate.plasma["B_ref"]
        aspect_rat = 1/self.powerstate.plasma["eps"]
        r_min = self.powerstate.plasma["a"]
        ni20 = self.powerstate.plasma["ni"] * 1e-1
        c_rad = self.powerstate.plasma["ions_set_c_rad"]
        Zi = self.powerstate.plasma["ions_set_Zi"]

        # ----------------------------------------------------
        # Bremsstrahlung + Line
        # ----------------------------------------------------

        # Calling chevychev polys only once for all the species at the same time, for speed
        Adas = adas_aurora(Te_keV, c_rad)
        Pcool = ne20 * (Adas * ni20.permute(2, 0, 1)).sum(dim=0) # Sum over species

        # ----------------------------------------------------
        # Bremsstrahlung
        # ----------------------------------------------------

        f = 0.005344  # 1.69e-32*(1E20*1E-6)**2*(1E3)**0.5
        self.powerstate.plasma["qrad_bremms"] = f * ne20 * (ni20 * Zi.unsqueeze(1)**2).sum(dim=-1) * Te_keV**0.5

        # ----------------------------------------------------
        # Line
        # ----------------------------------------------------

        # TGYRO "Trick": Calculate bremmstrahlung separate and substract to Pcool to get the actual line
        self.powerstate.plasma["qrad_line"] = Pcool - self.powerstate.plasma["qrad_bremms"]

        # ----------------------------------------------------
        # Synchrotron
        # ----------------------------------------------------
        self.powerstate.plasma["qrad_sync"] = PLASMAtools.synchrotron(Te_keV, ne20, b_ref, aspect_rat.unsqueeze(-1), r_min.unsqueeze(-1))

        # ----------------------------------------------------
        # Total radiation
        # ----------------------------------------------------

        self.powerstate.plasma["qrad"] = (
            self.powerstate.plasma["qrad_sync"] + self.powerstate.plasma["qrad_line"] + self.powerstate.plasma["qrad_bremms"]
        )

def adas_aurora(Te, c):
    """
    - This script calculates the cooling reate from ADAS data of impurity ions (erg cm^3/s), using Te (keV).
    - It follows the methodology in TGYRO [Candy et al. PoP 2009]. All the credits are due to the authors of TGYRO
    - Improvements have been made to make it faster, by taking into account array operations within pytorch rather than loops

    - Input comes as Te[batch,nR] and c[batch,nZ,nR]
    - Output comes as lz[nZ,batch,nR]
    """
    
    # Define Chebyshev grid
    precomputed_factor = 0.28953  # 2/torch.log(t1_adas/t0_adas), 50.0/0.05
    x = (-1.0 + precomputed_factor * torch.log(Te / 0.05)).clip(min=-1, max=1)

    # Chebyshev series ( T_k(x) = cos[k*arccos(x)] )
    precomputed_factor = 48.3542  # log( (1E20*1E-6)**2 * 1E-7 )
    iCoeff = torch.linspace(0, 11, 12).to(Te)

    lz = torch.exp(
        precomputed_factor
        + (
            c.permute(2, 1, 0)[...,None]
            * torch.cos(iCoeff[:, None, None, None] * torch.acos(x))
        ).sum(dim=0)
    )

    return lz


def get_chebyshev_coeffs(name):
    """
    This script calculates Chebyshev polynomial coefficients for each impurity ion, following entirely
    the methodology in TGYRO [Candy et al. PoP 2009]. All the credits are due to the authors of TGYRO
    """

    if name == "W":
        c = [
            -4.093426327035e01,
            -8.887660631564e-01,
            -3.780990284830e-01,
            -1.950023337795e-01,
            +3.138290691843e-01,
            +4.782989513315e-02,
            -9.942946187466e-02,
            +8.845089763161e-03,
            +9.069526573697e-02,
            -5.245048352825e-02,
            -1.487683353273e-02,
            +1.917578018825e-02,
        ]
    elif name == "Xe":
        c = [
            -4.126366679797e01,
            -1.789569183388e00,
            -2.380331458294e-01,
            +2.916911530426e-01,
            -6.217313390606e-02,
            +1.177929596352e-01,
            +3.114580325620e-02,
            -3.551020007260e-02,
            -4.850122964780e-03,
            +1.132323304719e-02,
            -5.275312157892e-02,
            -9.051568201374e-03,
        ]
    elif name == "Mo":
        c = [
            -4.178151951275e01,
            -1.977018529373e00,
            +5.339155696054e-02,
            +1.164267551804e-01,
            +3.697881990263e-01,
            -9.594816048640e-02,
            -1.392054581553e-01,
            +1.272648056277e-01,
            -1.336366483240e-01,
            +3.666060293888e-02,
            +9.586025795242e-02,
            -7.210209944439e-02,
        ]
    elif name == "Kr":
        c = [
            -4.235332287815e01,
            -1.508707679199e00,
            -3.300772886398e-01,
            +6.166385849657e-01,
            +1.752687990068e-02,
            -1.004626261246e-01,
            +5.175682671490e-03,
            -1.275380183939e-01,
            +1.087790584052e-01,
            +6.846942959545e-02,
            -5.558980841419e-02,
            -6.669294912560e-02,
        ]
    elif name == "Ni":
        c = [
            -4.269403899818e01,
            -2.138567547684e00,
            +4.165648766103e-01,
            +2.507972619622e-01,
            -1.454986877598e-01,
            +4.044612562765e-02,
            -1.231313167536e-01,
            +1.307076922327e-01,
            +1.176971646853e-01,
            -1.997449027896e-01,
            -8.027057678386e-03,
            +1.583614529900e-01,
        ]
    elif name == "Fe":
        c = [
            -4.277490044241e01,
            -2.232798257858e00,
            +2.871183684045e-01,
            +2.903760139426e-01,
            -4.662374777924e-02,
            -4.436273974526e-02,
            -1.004882554335e-01,
            +1.794710746088e-01,
            +3.168699330882e-02,
            -1.813266337535e-01,
            +5.762415716395e-02,
            +6.379542965373e-02,
        ]
    elif name == "Ca":
        c = [
            -4.390083075521e01,
            -1.692920511934e00,
            +1.896825846094e-01,
            +2.333977195162e-01,
            +5.307786998918e-02,
            -2.559420140904e-01,
            +4.733492400000e-01,
            -3.788430571182e-01,
            +3.375702537147e-02,
            +1.030183684347e-01,
            +1.523656115806e-02,
            -7.482021324342e-02,
        ]
    elif name == "Ar":
        c = [
            -4.412345259739e01,
            -1.788450950589e00,
            +1.322515262175e-01,
            +4.876947389538e-01,
            -2.869002749245e-01,
            +1.699452914498e-01,
            +9.950501421570e-02,
            -2.674585184275e-01,
            +7.451345261250e-02,
            +1.495713760953e-01,
            -1.089524173155e-01,
            -4.191575231760e-02,
        ]
    elif name == "Si":
        c = [
            -4.459983387390e01,
            -2.279998599897e00,
            +7.703525425589e-01,
            +1.494919348709e-01,
            -1.136851457700e-01,
            +2.767894295326e-01,
            -3.577491771736e-01,
            +7.013841334798e-02,
            +2.151919651291e-01,
            -2.052895326141e-01,
            +2.210085804088e-02,
            +9.270982150548e-02,
        ]
    elif name == "Al":
        c = [
            -4.475065090279e01,
            -2.455868594007e00,
            +9.468903008039e-01,
            +6.944445017599e-02,
            -4.550919134508e-02,
            +1.804382546971e-01,
            -3.573462505157e-01,
            +2.075274089736e-01,
            +1.024482383310e-01,
            -2.254367207993e-01,
            +1.150695613575e-01,
            +3.414328980459e-02,
        ]
    elif name == "Ne":
        c = [
            -4.599844680574e01,
            -1.684860164232e00,
            +9.039325377493e-01,
            -7.544604235334e-02,
            +2.849631706915e-01,
            -4.827471944126e-01,
            +3.138177972060e-01,
            +2.876874062690e-03,
            -1.809607030192e-01,
            +1.510609882754e-01,
            -2.475867654255e-02,
            -6.269602018004e-02,
        ]
    elif name == "F":
        c = [
            -4.595870691474e01,
            -2.176917325041e00,
            +1.176783264877e00,
            -7.712313240060e-02,
            +1.847534287214e-01,
            -4.297192280031e-01,
            +3.374503944631e-01,
            -5.862051731844e-02,
            -1.363051725174e-01,
            +1.580531615737e-01,
            -7.677594113938e-02,
            -5.498186771891e-03,
        ]
    elif name == "N":
        c = [
            -4.719917668483e01,
            -1.128938430123e00,
            +5.686617156868e-01,
            +5.565647850806e-01,
            -6.103105546858e-01,
            +2.559496676285e-01,
            +3.204394187397e-02,
            -1.347036917773e-01,
            +1.166192946931e-01,
            -6.001774708924e-02,
            +1.078186024405e-02,
            +1.336864982060e-02,
        ]
    elif name == "O":
        c = [
            -4.688092238361e01,
            -1.045540847894e00,
            +3.574644442831e-01,
            +6.007860794100e-01,
            -3.812470436912e-01,
            -9.944716626912e-02,
            +3.141455586422e-01,
            -2.520592337580e-01,
            +9.745206757309e-02,
            +1.606664371633e-02,
            -5.269687016804e-02,
            +3.726780755484e-02,
        ]
    elif name == "C":
        c = [
            -4.752370087442e01,
            -1.370806613078e00,
            +1.119762977201e00,
            +6.244262441360e-02,
            -4.172077577493e-01,
            +3.237504483005e-01,
            -1.421660253114e-01,
            +2.526893756273e-02,
            +2.320010310338e-02,
            -3.487271688767e-02,
            +2.758311539699e-02,
            -1.063180164276e-02,
        ]
    elif name == "Be":
        c = [
            -4.883447566291e01,
            -8.543314577695e-01,
            +1.305444973614e00,
            -4.830394934711e-01,
            +1.005512839480e-01,
            +1.392590190604e-02,
            -1.980609625444e-02,
            +5.342857189984e-03,
            +2.324970825974e-03,
            -2.466382923947e-03,
            +1.073116177574e-03,
            -9.834117466066e-04,
        ]
    elif name == "He":
        c = [
            -5.128490291648e01,
            +7.743125302555e-01,
            +4.674917416545e-01,
            -2.087203609904e-01,
            +7.996303682551e-02,
            -2.450841492530e-02,
            +4.177032799848e-03,
            +1.109529527611e-03,
            -1.080271138220e-03,
            +1.914061606095e-04,
            +2.501544833223e-04,
            -3.856698155759e-04,
        ]
    elif name == "H" or name == "D" or name == "T" or name == "DT":
        c = [
            -5.307012989032e01,
            +1.382271913121e00,
            +1.111772196884e-01,
            -3.989144654893e-02,
            +1.043427394534e-02,
            -3.038480967797e-03,
            +5.851591993347e-04,
            +3.472228652286e-04,
            -8.418918897927e-05,
            +3.973067124523e-05,
            -3.853620366361e-05,
            +2.005063821667e-04,
        ]

    else:
        print(
            f"\t- Specie {name} not found in ADAS database, assuming zero radiation from it",
            typeMsg="w",
        )
        c = [-1e10, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]

    return c

def sigv_fun(ti):
    """
    This script calculates the DT fusion reaction rate coefficient (cm^3/s) from ti (keV), following
    [H.-S. Bosch and G.M. Hale, Nucl. Fusion 32 (1992) 611]

    This method follows the same methodology as in TGYRO [Candy et al. PoP 2009] and all the credits
    are due to the authors of TGYRO. From the source code, this function follows the same procedures
    as in tgyro_auxiliary_routines.f90.
    """

    r0 = ti * (c2 + ti * (c4 + ti * c6)) / (1.0 + ti * (c3 + ti * (c5 + ti * c7)))
    theta = ti / (1.0 - r0)
    xi = (bg**2 / (4.0 * theta)) ** (1.0 / 3.0)

    sigv = c1 * theta * (xi / (er * ti**3)) ** 0.5 * torch.exp(-3.0 * xi)

    return sigv


def sivukhin(x, n=12):
    """
    This script implements the TGYRO's sivukhin algorithm.
    This method follows the same methodology as in TGYRO [Candy et al. PoP 2009] and all the credits
    are due to the authors of TGYRO.

    Improvements have been made to make it faster, by taking into account
    array operations within pytorch rather than loops
    """

    # --------------
    # Asymptotes
    # --------------

    v = 0.866025  # sin(2*pi/3)
    f = (2 * pi / 3) / v - 2.0 / x**0.5 + 0.5 / (x * x)
    sivukhin1 = f / x

    sivukhin3 = 1.0 - 0.4 * x**1.5

    # --------------
    # Numerical (middle)
    # --------------

    dy = x / (n - 1)
    f = 0.0
    for i in range(n):
        yi = i * dy
        if i == 0 or i == n - 1:
            f = f + 0.5 / (1.0 + yi**1.5)
        else:
            f = f + 1.0 / (1.0 + yi**1.5)
    f = f * dy

    sivukhin2 = f / x

    # --------------
    # Construct
    # --------------

    sivukhin = (
        (x > 4.0) * sivukhin1
        + (x < 4.0) * (x > 0.1) * sivukhin2
        + (x < 0.1) * sivukhin3
    )

    return sivukhin
