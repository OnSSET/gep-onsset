# Defines the modules

import logging
import os
import numpy as np
import itertools

import pandas as pd
from onsset import (SET_GRID_PENALTY, SET_WINDVEL, SET_WINDCF, SET_GHI, HOURS_PER_YEAR,
                    SET_HYDRO_DIST, SettlementProcessor, Technology)

try:
    from onsset.specs import (SPE_COUNTRY, SPE_ELEC, SPE_ELEC_MODELLED,
                              SPE_ELEC_RURAL, SPE_ELEC_URBAN, SPE_END_YEAR,
                              SPE_GRID_CAPACITY_INVESTMENT, SPE_GRID_LOSSES,
                              SPE_MAX_GRID_EXTENSION_DIST,
                              SPE_NUM_PEOPLE_PER_HH_RURAL,
                              SPE_NUM_PEOPLE_PER_HH_URBAN, SPE_POP, SPE_POP_FUTURE,
                              SPE_START_YEAR, SPE_URBAN, SPE_URBAN_FUTURE,
                              SPE_URBAN_MODELLED)
except ImportError:
    from specs import (SPE_COUNTRY, SPE_ELEC, SPE_ELEC_MODELLED,
                       SPE_ELEC_RURAL, SPE_ELEC_URBAN, SPE_END_YEAR,
                       SPE_GRID_CAPACITY_INVESTMENT, SPE_GRID_LOSSES,
                       SPE_MAX_GRID_EXTENSION_DIST,
                       SPE_NUM_PEOPLE_PER_HH_RURAL,
                       SPE_NUM_PEOPLE_PER_HH_URBAN, SPE_POP, SPE_POP_FUTURE,
                       SPE_START_YEAR, SPE_URBAN, SPE_URBAN_FUTURE,
                       SPE_URBAN_MODELLED)
from openpyxl import load_workbook

logging.basicConfig(format='%(asctime)s\t\t%(message)s', level=logging.DEBUG)


def calibration(specs_path, csv_path, specs_path_calib, calibrated_csv_path):
    """

    Arguments
    ---------
    specs_path
    csv_path
    specs_path_calib
    calibrated_csv_path
    """
    specs_data = pd.read_excel(specs_path, sheet_name='SpecsData')
    settlements_in_csv = csv_path
    settlements_out_csv = calibrated_csv_path

    onsseter = SettlementProcessor(settlements_in_csv)

    num_people_per_hh_rural = float(specs_data.iloc[0][SPE_NUM_PEOPLE_PER_HH_RURAL])
    num_people_per_hh_urban = float(specs_data.iloc[0][SPE_NUM_PEOPLE_PER_HH_URBAN])

    # RUN_PARAM: these are the annual household electricity targets
    tier_1 = 38.7  # 38.7 refers to kWh/household/year. It is the mean value between Tier 1 and Tier 2
    tier_2 = 219
    tier_3 = 803
    tier_4 = 2117
    tier_5 = 2993

    onsseter.prepare_wtf_tier_columns(num_people_per_hh_rural, num_people_per_hh_urban,
                                      tier_1, tier_2, tier_3, tier_4, tier_5)
    onsseter.condition_df()
    onsseter.df[SET_GRID_PENALTY] = onsseter.grid_penalties(onsseter.df)

    onsseter.df[SET_WINDCF] = onsseter.calc_wind_cfs(onsseter.df[SET_WINDVEL])

    pop_actual = specs_data.loc[0, SPE_POP]
    urban_current = specs_data.loc[0, SPE_URBAN]
    start_year = int(specs_data.loc[0, SPE_START_YEAR])
    elec_actual = specs_data.loc[0, SPE_ELEC]
    elec_actual_urban = specs_data.loc[0, SPE_ELEC_URBAN]
    elec_actual_rural = specs_data.loc[0, SPE_ELEC_RURAL]

    pop_modelled, urban_modelled = onsseter.calibrate_current_pop_and_urban(pop_actual, urban_current)

    specs_data.loc[0, SPE_URBAN_MODELLED] = urban_modelled

    elec_calibration_results = onsseter.calibrate_elec_current(elec_actual, elec_actual_urban, elec_actual_rural,
                                                               start_year, buffer=True)

    specs_data.loc[0, SPE_ELEC_MODELLED] = elec_calibration_results[0]
    specs_data.loc[0, 'rural_elec_ratio_modelled'] = elec_calibration_results[1]
    specs_data.loc[0, 'urban_elec_ratio_modelled'] = elec_calibration_results[2]
    specs_data['grid_data_used'] = elec_calibration_results[3]
    specs_data['grid_distance_used'] = elec_calibration_results[4]
    specs_data['ntl_limit'] = elec_calibration_results[5]
    specs_data['pop_limit'] = elec_calibration_results[6]
    specs_data['Buffer_used'] = elec_calibration_results[7]
    specs_data['buffer_distance'] = elec_calibration_results[8]

    book = load_workbook(specs_path)
    writer = pd.ExcelWriter(specs_path_calib, engine='openpyxl')
    writer.book = book
    # RUN_PARAM: Here the calibrated "specs" data are copied to a new tab called "SpecsDataCalib". 
    # This is what will later on be used to feed the model
    specs_data.to_excel(writer, sheet_name='SpecsDataCalib', index=False)
    writer.save()
    writer.close()

    logging.info('Calibration finished. Results are transferred to the csv file')
    onsseter.df.to_csv(settlements_out_csv, index=False)


def scenario(specs_path, calibrated_csv_path, results_folder, summary_folder,
             gis_costs_path='', power_cost_path='', save_shapefiles=False, gis_grid_extension=False,
             dist_network_detail=False):
    """

    Arguments
    ---------
    specs_path : str
    calibrated_csv_path : str
    results_folder : str
    summary_folder : str

    """

    if gis_grid_extension:
        import onsset_gis

    scenario_info = pd.read_excel(specs_path, sheet_name='ScenarioInfo')
    scenarios = scenario_info['Scenario']
    scenario_parameters = pd.read_excel(specs_path, sheet_name='ScenarioParameters')
    specs_data = pd.read_excel(specs_path, sheet_name='SpecsDataCalib', index_col=0)
    print(specs_data.iloc[0][SPE_COUNTRY])

    scenario_params = scenario_parameters.columns.tolist()
    try:
        scenario_params.remove('Unnamed: 0')
    except ValueError:
        pass

    for scenario in scenarios:

        print('Scenario: ' + str(scenario + 1))

        yearsofanalysis = specs_data.index.tolist()
        base_year = specs_data.iloc[0][SPE_START_YEAR]
        end_year = yearsofanalysis[-1]

        start_years = [base_year] + yearsofanalysis

        time_steps = {}
        for year in range(len(yearsofanalysis)):
            time_steps[yearsofanalysis[year]] = yearsofanalysis[year] - start_years[year]

        onsseter = SettlementProcessor(calibrated_csv_path)

        country_id = specs_data.iloc[0]['CountryCode']

        # ToDo project pop for each year based on previous year
        pop_future = specs_data.iloc[0][SPE_POP_FUTURE]
        urban_future = specs_data.iloc[0][SPE_URBAN_FUTURE]

        # ToDo make more flexible to read all from one sheet ???
        pop_index = scenario_info.iloc[scenario]['Population_Growth']
        tier_index = scenario_info.iloc[scenario]['Target_electricity_consumption_level']
        grid_index = scenario_info.iloc[scenario]['Grid_electricity_generation_cost']
        pv_index = scenario_info.iloc[scenario]['PV_cost_adjust']
        diesel_index = scenario_info.iloc[scenario]['Diesel_price']
        productive_index = scenario_info.iloc[scenario]['Productive_uses_demand']
        prio_index = scenario_info.iloc[scenario]['Prioritization_algorithm']

        end_year_pop = scenario_parameters.iloc[pop_index]['PopEndYear']
        rural_tier = scenario_parameters.iloc[tier_index]['RuralTargetTier']
        urban_tier = scenario_parameters.iloc[tier_index]['UrbanTargetTier']
        grid_price = scenario_parameters.iloc[grid_index]['GridGenerationCost']
        pv_capital_cost_adjust = scenario_parameters.iloc[pv_index]['PV_Cost_adjust']
        diesel_price = scenario_parameters.iloc[diesel_index]['DieselPrice']
        productive_demand = scenario_parameters.iloc[productive_index]['ProductiveDemand']
        prioritization = scenario_parameters.iloc[prio_index]['PrioritizationAlgorithm']
        auto_intensification = scenario_parameters.iloc[prio_index]['AutoIntensificationKM']

        settlements_out_csv = os.path.join(results_folder,
                                           '{}-1-{}_{}_{}_{}_{}_{}.csv'.format(country_id, pop_index, tier_index,
                                                                               1, grid_index, pv_index,
                                                                               prio_index))
        summary_csv = os.path.join(summary_folder,
                                   '{}-1-{}_{}_{}_{}_{}_{}_summary.csv'.format(country_id, pop_index, tier_index,
                                                                               1, grid_index, pv_index,
                                                                               prio_index))


        elements = ["1.Population", "2.New_Connections", "3.Capacity", "4.Investment"]
        tech_names = ["Grid", "SA_Diesel", "SA_PV", "MG_Diesel", "MG_PV", "MG_Wind", "MG_Hydro", "MG_PV_Hybrid"]
        tech_codes = {"Grid": 1, "SA_Diesel": 2, "SA_PV": 3, "MG_Diesel": 4, "MG_PV": 5, "MG_Wind": 6, "MG_Hydro": 7,
                      "MG_PV_Hybrid": 8}

        # RunParam: define the technologes to be included in the analysis
        tech_names = ["Grid", "SA_PV", "MG_PV", "MG_Wind", "MG_Hydro"]

        sumtechs = []
        for element in elements:
            for tech in tech_names:
                sumtechs.append(element + "_" + tech)
        total_rows = len(sumtechs)
        df_summary = pd.DataFrame(columns=yearsofanalysis)
        for row in range(0, total_rows):
            df_summary.loc[sumtechs[row]] = "Nan"

        # onsseter.df.loc[onsseter.df['MV']]

        onsseter.current_mv_line_dist()

        onsseter.project_pop_and_urban(pop_future, urban_future, base_year, yearsofanalysis)

        if gis_grid_extension:
            onsseter.df = onsset_gis.create_geodataframe(onsseter.df)

        for year in yearsofanalysis:
            time_step = time_steps[year]
            start_year = year - time_step

            num_people_per_hh_rural = float(specs_data.loc[year][SPE_NUM_PEOPLE_PER_HH_RURAL])
            num_people_per_hh_urban = float(specs_data.loc[year][SPE_NUM_PEOPLE_PER_HH_URBAN])
            max_grid_extension_dist = float(specs_data.loc[year][SPE_MAX_GRID_EXTENSION_DIST])
            eleclimit = specs_data.loc[year]['ElecTarget']
            annual_new_grid_connections_limit = specs_data.loc[year]['GridConnectionsLimitThousands'] * 1000
            annual_grid_cap_gen_limit = specs_data.loc[year]['NewGridGenerationCapacityAnnualLimitMW'] * 1000

            grid_cap_gen_limit = time_step * annual_grid_cap_gen_limit
            grid_connect_limit = time_step * annual_new_grid_connections_limit

            # RUN_PARAM: Fill in general and technology specific parameters (e.g. discount rate, losses etc.)
            Technology.set_default_values(base_year=base_year,
                                          start_year=start_year,
                                          end_year=end_year,
                                          discount_rate=0.08,
                                          detailed=dist_network_detail)

            grid_calc = Technology(om_of_td_lines=0.02,
                                   distribution_losses=float(specs_data.iloc[0][SPE_GRID_LOSSES]),
                                   connection_cost_per_hh=125,
                                   base_to_peak_load_ratio=0.8,
                                   capacity_factor=1,
                                   tech_life=30,
                                   grid_capacity_investment=float(specs_data.iloc[0][SPE_GRID_CAPACITY_INVESTMENT]),
                                   grid_penalty_ratio=1,
                                   grid_price=grid_price)

            mg_hydro_calc = Technology(om_of_td_lines=0.02,
                                       distribution_losses=0.05,
                                       connection_cost_per_hh=100,
                                       base_to_peak_load_ratio=0.85,
                                       capacity_factor=0.5,
                                       tech_life=30,
                                       capital_cost={float("inf"): 3000},
                                       om_costs=0.03,
                                       additional_mv_line_length=onsseter.df[SET_HYDRO_DIST],
                                       mini_grid=True)

            mg_wind_calc = Technology(om_of_td_lines=0.02,
                                      distribution_losses=0.05,
                                      connection_cost_per_hh=100,
                                      base_to_peak_load_ratio=0.85,
                                      capacity_factor=onsseter.df[SET_WINDCF],
                                      capital_cost={float("inf"): 3750},
                                      om_costs=0.02,
                                      tech_life=20,
                                      mini_grid=True)

            mg_pv_calc = Technology(om_of_td_lines=0.02,
                                    distribution_losses=0.05,
                                    connection_cost_per_hh=100,
                                    base_to_peak_load_ratio=0.85,
                                    capacity_factor=onsseter.df[SET_GHI] / HOURS_PER_YEAR,
                                    tech_life=20,
                                    om_costs=0.015,
                                    capital_cost={float("inf"): 2950 * pv_capital_cost_adjust},
                                    mini_grid=True)

            sa_pv_calc = Technology(base_to_peak_load_ratio=0.9,
                                    capacity_factor=onsseter.df[SET_GHI] / HOURS_PER_YEAR,
                                    tech_life=15,
                                    om_costs=0.02,
                                    capital_cost={float("inf"): 6950 * pv_capital_cost_adjust,
                                                  1: 4470 * pv_capital_cost_adjust,
                                                  0.100: 6380 * pv_capital_cost_adjust,
                                                  0.050: 8780 * pv_capital_cost_adjust,
                                                  0.020: 9620 * pv_capital_cost_adjust
                                                  },
                                    standalone=True)

            mg_diesel_calc = Technology(om_of_td_lines=0.02,
                                        distribution_losses=0.05,
                                        connection_cost_per_hh=100,
                                        base_to_peak_load_ratio=0.85,
                                        capacity_factor=0.7,
                                        tech_life=15,
                                        om_costs=0.1,
                                        capital_cost={float("inf"): 721},
                                        mini_grid=True)

            sa_diesel_calc = Technology(base_to_peak_load_ratio=0.9,
                                        capacity_factor=0.5,
                                        tech_life=10,
                                        om_costs=0.1,
                                        capital_cost={float("inf"): 938},
                                        standalone=True)

            sa_diesel_cost = {'diesel_price': diesel_price,
                              'efficiency': 0.28,
                              'diesel_truck_consumption': 14,
                              'diesel_truck_volume': 300}

            mg_diesel_cost = {'diesel_price': diesel_price,
                              'efficiency': 0.33,
                              'diesel_truck_consumption': 33.7,
                              'diesel_truck_volume': 15000}

            onsseter.set_scenario_variables(year, num_people_per_hh_rural, num_people_per_hh_urban, time_step,
                                            start_year, urban_tier, rural_tier, end_year_pop, productive_demand)

            onsseter.diesel_cost_columns(sa_diesel_cost, mg_diesel_cost, year)

            if 'MG_PV_Hybrid' in tech_names:

                hybrid_lcoe, hybrid_capacity, hybrid_investment = onsseter.pv_hybrids_lcoe(year)

                mg_pv_hybrid_calc = Technology(om_of_td_lines=0.02,
                                               distribution_losses=0.05,
                                               connection_cost_per_hh=100,
                                               capacity_factor=0.5,
                                               base_to_peak_load_ratio=0.85,  # ToDo
                                               tech_life=20,
                                               mini_grid=True,
                                               hybrid_fuel=hybrid_lcoe,
                                               hybrid_investment=hybrid_investment,
                                               hybrid_capacity=hybrid_capacity,
                                               hybrid=True)

                tech_calcs = {'Grid': grid_calc,
                              "SA_Diesel": sa_diesel_calc,
                              "SA_PV": sa_pv_calc,
                              "MG_Diesel": mg_diesel_calc,
                              "MG_PV": mg_pv_calc,
                              "MG_Wind": mg_wind_calc,
                              "MG_Hydro": mg_hydro_calc,
                              "MG_PV_Hybrid": mg_pv_hybrid_calc}

            else:
                tech_calcs = {'Grid': grid_calc,
                              "SA_Diesel": sa_diesel_calc,
                              "SA_PV": sa_pv_calc,
                              "MG_Diesel": mg_diesel_calc,
                              "MG_PV": mg_pv_calc,
                              "MG_Wind": mg_wind_calc,
                              "MG_Hydro": mg_hydro_calc}

            investments, capacities = onsseter.calculate_off_grid_lcoes(tech_calcs, year, end_year,
                                                                        time_step, tech_names, tech_codes)

            grid_investment, grid_capacity, grid_cap_gen_limit, grid_connect_limit = \
                onsseter.pre_electrification(grid_price, year, time_step, end_year, grid_calc, grid_cap_gen_limit,
                                             grid_connect_limit)

            if gis_grid_extension:
                print('Running pathfinder for grid extensions')
                onsseter.df['extension_distance_' + '{}'.format(year)] = 99

                onsseter.pre_screening(eleclimit, year, time_step, prioritization, auto_intensification)

                #grid_investment = np.zeros(len(onsseter.df['X_deg']))
                onsseter.max_extension_dist(year, time_step, end_year, start_year, grid_calc)

                onsseter.df = onsset_gis.find_grid_path(onsseter.df, year, time_step, start_year, grid_connect_limit,
                                                        grid_cap_gen_limit, gis_costs_path, power_cost_path,
                                                        max_grid_extension_dist, results_folder, save_shapefiles)

                grid_investment, grid_capacity = \
                    onsseter.elec_extension_gis(grid_calc, max_grid_extension_dist, year, start_year, end_year,
                                                time_step, new_investment=grid_investment, new_capacity=grid_capacity)
            else:
                grid_investment, grid_capacity = \
                    onsseter.elec_extension(grid_calc, max_grid_extension_dist, year, start_year, end_year, time_step,
                                            grid_cap_gen_limit, grid_connect_limit,
                                            auto_intensification=auto_intensification, prioritization=prioritization,
                                            new_investment=grid_investment, new_capacity=grid_capacity)

            onsseter.results_columns(tech_names, tech_codes, year, time_step, prioritization, auto_intensification)

            onsseter.calculate_investments_and_capacity(investments, capacities, grid_investment, grid_capacity, year,
                                                        tech_names, tech_codes)

            onsseter.apply_limitations(eleclimit, year, time_step, prioritization, auto_intensification)

            onsseter.calc_summaries(df_summary, sumtechs, tech_names, tech_codes, year)

        for i in onsseter.df.columns:
            if onsseter.df[i].dtype == 'float64':
                onsseter.df[i] = pd.to_numeric(onsseter.df[i], downcast='float')
            elif onsseter.df[i].dtype == 'int64':
                onsseter.df[i] = pd.to_numeric(onsseter.df[i], downcast='signed')

        df_summary.to_csv(summary_csv, index=sumtechs)
        onsseter.df.to_csv(settlements_out_csv, index=False)

        logging.info('Finished')
