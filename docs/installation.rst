============
Installation
============

.. contents::
	:local:
	:depth: 1

.. attention::
   MITIM requires python>=3.9, a requirement driven by the optimization capabilities in PyTorch.
   If you do not have python>=3.9 but still want to use MITIM's non-optimization features, you may try to install each python package individually (see ``setup.py`` file) and skip ``botorch``. However, this option is not supported and there is no assurance the code will work.

Instructions
------------

Clone the `GitHub repository  <https://github.com/pabloprf/MITIM-fusion>`_ (do not forget to select the appropriate settings to receive notifications of new releases and announcements, and **Star** the repository to increase its visibility):

.. code-block:: console

   git clone git@github.com:pabloprf/MITIM-fusion.git

.. hint::
   
   It may be useful, at this point, to create a virtual environment to install required MITIM dependencies. For example, using python's ``venv`` package:

   .. code-block:: console

      python3.9 -m venv mitim-env
      source mitim-env/bin/activate
      pip3 install pip --upgrade

Use ``pip3`` to install all the required MITIM requirements:

.. code-block:: console

   pip3 install -e MITIM-fusion[pyqt]

.. note::
   
   The optional argument ``[pyqt]`` added in the intallation command above must only be used if the machine allows for graphic interfaces.
   If running in a computing cluster, remove that flag.
   The ``pyqt`` package is used to create condensed figures into a single notebook when interpreting and plotting simulation results.
   
   If you wish to install all capabilities (including compatibility with the `OMFIT <https://omfit.io/>`_  or `FREEGS <https://github.com/freegs-plasma/freegs>`_ codes), it is recommended that ``pip3`` is run as follows:

   .. code-block:: console

      pip3 install -e MITIM-fusion[pyqt,omfit,freegs]


If you were unsuccessful in the installation, check out our :ref:`Frequently Asked Questions` section.


User configuration
------------------

In ``MITIM-fusion/config/``, there is a ``config_user_example.json`` with specifications of where to run certain codes and what the login requirements are. **If you are planning on using MITIM to run plasma simulation codes**, please create an equivalent file ``config_user.json`` in the same folder, indicating your specific needs.

.. code-block:: console

   cp MITIM-fusion/config/config_user_example.json MITIM-fusion/config/config_user.json

Apart from machine configurations, ``preferences`` in ``config_user.json`` also includes a ``verbose_level`` flag, which indicates the amount of messages that are printed to the terminal when running MITIM.
For debugging purposes, it is recommended a maximum verbose level of ``5``.
For production runs, a minimum verbose level of ``1`` is recommended so that you only get important messages.
``preferences`` also allows a ``dpi_notebook`` value (in percent from standard), which should be adjusted for each user's screen configuration if the MITIM notebook figures are too small or too large.

This is an example of a ``config_user.json`` file that specifies that TGLF should be run in the *eofe7.mit.edu* machine and TGYRO in the *perlmutter.nersc.gov* machine.
The ``slurm`` options are only required if you are running in a computing cluster that uses the SLURM scheduler, and you can specify the partition, account, nodes to exclude and default memory requirements.
In this example, the ``identity`` option is only required if you are running in a computing cluster that requires a specific SSH key to access it.

.. code-block:: console
   
   {
      "preferences": {
         "tglf":             "engaging",
         "tgyro":            "perlmutter",
         "verbose_level":    "5",
         "dpi_notebook":     "80"
      },
      "engaging": {
         "machine":          "eofe7.mit.edu", 
         "username":         "YOUR_USERNAME",
         "scratch":          "/pool001/YOUR_USERNAME/scratch/",
         "slurm": {
            "partition":    "sched_mit_psfc",
            "exclude":      "node584"
            }
      },
      "perlmutter": {
         "machine":          "perlmutter.nersc.gov", 
         "username":         "YOUR_USERNAME",
         "scratch":          "/pscratch/sd/p/YOUR_USERNAME/scratch/",
         "identity":         "/Users/YOUR_USERNAME/.ssh/id_rsa_nersc",
         "slurm": {
               "account":      "YOUR_ACCOUNT",
               "partition":    "YOUR_PARTITION",
               "constraint":   "gpu",
               "mem":          "4GB" 
            }
      }
   }

If you select to run a code in a given machine, please make sure you have ssh rights to that machine with the login instructions specified, unless you are running it locally.
MITIM will attempt to create SSH and SFTP connections to that machine, and will ask for the password if it is not available in the SSH keys or via a proxy connection.

.. attention::

   Note that MITIM does not maintain or develop the simulation codes that are used within it, such as those from `GACODE <http://gafusion.github.io/doc/index.html>`_ or `TRANSP <hhttps://transp.pppl.gov/index.html>`_. It assumes that proper permissions have been obtained and that working versions of those codes exist in the machine configured to run them.

Please note that MITIM will try to run the codes with standard commands that the shell must understand.
For example, to run the TGLF code, MITIM will want to execute the command ``tglf`` in the *eofe7.mit.edu* machine as specified in the example above.
There are several ways to make sure that the shell understands the command:

.. dropdown:: 1. Use MITIM automatic machine configuration (limited)

   First, MITIM will automatically try to source ``$MITIM_PATH/config/mitim.bashrc``. If the machine you are running the code
   in is listed in ``$MITIM_PATH/config/machine_sources/``, this will also source a machine-specific file.
   Specifications to run certain codes (e.g. the GACODE suite) could be available there, but the number of machines that are
   automatically available in the public repository is, obviously, limited.

   Please note that this option is only valid if the **MITIM repository and the environment variable $MITIM_PATH are available also in that machine, pointing to the MITIM-fusion folders** (not only from the one you are launching the code).
   However, if you prefer to use options 2 or 3, the sourcing of a non-existing file will not cause any issues.

.. dropdown:: 2. Source at shell initialization (recommended)

   Is the commands are available upon login in that machine (e.g. in your personal ``.bashrc`` file), MITIM will be able to run them.
   Please note that aliases are usually not available in non-interactive shells, and it is recommended to use full paths and to avoid print (echo) statements.

.. dropdown:: 3. Send specific commands per code

   Finally, you can populate the ``modules`` option per machine in your ``config_user.json`` file. For example:

   .. code-block:: console

      "engaging": {
         ...
         "modules": "export GACODE_ROOT=/home/$USER/gacode && . ${GACODE_ROOT}/shared/bin/gacode_setup"
         ...
      }

   MITIM will execute those commands immediately after ``source $MITIM_PATH/config/mitim.bashrc`` and before running any code.

   Note that you can the same machine listed several times in your ``config_user.json`` file, with different ``modules`` options per code.
   You just need to give it a different name per code.



License and contributions
-------------------------

MITIM is released under the MIT License, one of the most permissive and widely used open-source software licenses.
Our choice of this license aims to make the package as useful and applicable as possible, in support of the development of fusion energy.
Embracing the spirit of open-source collaboration, we appreciate users who help increase the visibility of our project by
starring the `MITIM-fusion <https://github.com/pabloprf/MITIM-fusion/>`_ GitHub repository and support and acknowledge the continuous development of this tool by citing the following works in any publications, talks and posters:

**[1]** P. Rodriguez-Fernandez, N.T. Howard, A. Saltzman, S. Kantamneni, J. Candy, C. Holland, M. Balandat, S. Ament and A.E. White, `Enhancing predictive capabilities in fusion burning plasmas through surrogate-based optimization in core transport solvers <https://arxiv.org/abs/2312.12610>`_, arXiv:2312.12610 (2023).

**[2]** P. Rodriguez-Fernandez, N.T. Howard and J. Candy, `Nonlinear gyrokinetic predictions of SPARC burning plasma profiles enabled by surrogate modeling <https://iopscience.iop.org/article/10.1088/1741-4326/ac64b2>`_, Nucl. Fusion 62, 076036 (2022).

These publications provide foundational insights and methodologies that have significantly contributed to the development of MITIM.

License
~~~~~~~

.. literalinclude:: LICENSE
   :language: text