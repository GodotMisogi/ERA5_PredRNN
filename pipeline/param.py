# data= \
# {
#     'product_type': [
#         'reanalysis',
#     ],
#     'variable': [
#         '10m_u_component_of_wind', '10m_v_component_of_wind', '2m_temperature',
#         'surface_pressure', 'total_precipitation',
#         # 'vertical_integral_of_potential_internal_and_latent_energy', # moist static energy (DNE)
#         'geopotential 500', # geopotential height @ 500 hPa (need a space to denote pressure level - no spaces in other variables!)
#         'vertical_integral_of_potential_and_internal_energy', # dry static energy
#         # will split these up and download separately
#     ],
#     'year': '2021', # last year of data
#     'month': [      # will download these months separately
#         '01', '02', '03',
#         '04', '05', '06',
#         '07', '08', '09',
#         '10', '11', '12',
#     ],
#     # 'month': ['01'],
#     'day': [        # days and times are downloaded together
#         '01', '02', '03',
#         '04', '05', '06',
#         '07', '08', '09',
#         '10', '11', '12',
#         '13', '14', '15',
#         '16', '17', '18',
#         '19', '20', '21',
#         '22', '23', '24',
#         '25', '26', '27',
#         '28', '29', '30',
#         '31',
#     ],
#     # 'day': [
#     #     '01', '02', '03',
#     #     '04', '05', '06',
#     #     '07'],
#     # 'time': [
#     #     '00:00', '01:00', '02:00',
#     #     '03:00', '04:00', '05:00',
#     #     '06:00', '07:00', '08:00',
#     #     '09:00', '10:00', '11:00',
#     #     '12:00', '13:00', '14:00',
#     #     '15:00', '16:00', '17:00',
#     #     '18:00', '19:00', '20:00',
#     #     '21:00', '22:00', '23:00',
#     # ],
#     'time': [
#         '00:00',
#         '06:00', 
#         '12:00', 
#         '18:00',
#     ],
#     'format': 'grib',
# }

data = \
{
    'variable': [
        'pde_u',
    ],
    't_step': 1080,
    'dt': 5e-3,
    'nvar': 1,
    'gshape': [64, 64],
}