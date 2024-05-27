Configuration
#############

Configuration options are loaded from a `microscope.toml` file.

pinout
------

See :doc:`digital_io` for pin definitions

Example:

.. code:: console

    [pinout]
    ext_ebeam_enable = 2


mag_cal
-------

m_per_hfov: theoretical meters per horizontal field of view at magnification 1. a one-point calibration curve

Example:

.. code:: console
    
    [mag_cal]
    m_per_hfov = 1234e-5