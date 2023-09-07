# Defines the modules

import logging
import os
import time

import pandas as pd
from onsset import (SET_ELEC_ORDER, SET_LCOE_GRID, SET_MIN_GRID_DIST, SET_GRID_PENALTY,
                    SET_MV_CONNECT_DIST, SET_WINDVEL, SET_WINDCF, SettlementProcessor, Technology)

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

logging.basicConfig(format='%(asctime)s\t\t%(message)s', level=logging.ERROR)


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


def scenario(specs_path, calibrated_csv_path, results_folder, summary_folder):
    """

    Arguments
    ---------
    specs_path : str
    calibrated_csv_path : str
    results_folder : str
    summary_folder : str

    """

    scenario_info = pd.read_excel(specs_path, sheet_name='ScenarioInfo')
    scenarios = scenario_info['Scenario']
    scenario_parameters = pd.read_excel(specs_path, sheet_name='ScenarioParameters')
    specs_data = pd.read_excel(specs_path, sheet_name='SpecsDataCalib', index_col=0)
    # print(specs_data.iloc[0, SPE_COUNTRY])

    for scenario in scenarios:
        print('Scenario: ' + str(scenario + 1), time.ctime())

        yearsofanalysis = specs_data.index.tolist()
        base_year = specs_data.iloc[0][SPE_START_YEAR]
        end_year = yearsofanalysis[-1]

        start_years = [base_year] + yearsofanalysis

        time_steps = {}
        for year in range(len(yearsofanalysis)):
            time_steps[yearsofanalysis[year]] = yearsofanalysis[year] - start_years[year]

        grid_option = scenario_info.iloc[scenario]['GridOption']
        transmission_investment = scenario_parameters.iloc[grid_option]['TransmissionCost']

        settlements_in_csv = calibrated_csv_path
        onsseter = SettlementProcessor(settlements_in_csv)
        onsseter.df.fillna(1, inplace=True)

        elements = ["1.Population", "2.New_Connections", "3.Capacity", "4.Investment", "5.Total_Costs", "6.Demand",
                    "7.Demand_LCOE", '8.all_costs', '9.all_costs_discounted', '10.gen', '11.discounted_gen']
        techs = ["Grid", "SA_Diesel", "SA_PV", "MG_Diesel", "MG_PV", "MG_Wind", "MG_Hydro", "MG_PV_Hybrid", "MG_Wind_Hybrid"]
        tech_codes = [1, 2, 3, 4, 5, 6, 7, 8, 9]

        techs = ["Grid", "SA_Diesel", "SA_PV", "MG_Diesel", "MG_PV", "MG_Wind", "MG_Hydro", "MG_PV_Hybrid"]
        tech_codes = [1, 2, 3, 4, 5, 6, 7, 8]

        sumtechs = []
        for element in elements:
            for tech in techs:
                sumtechs.append(element + "_" + tech)
        sumtechs.append('TotalCost')
        sumtechs.append('TotalDiscountedCost')
        sumtechs.append('LCOE')
        total_rows = len(sumtechs)
        df_summary = pd.DataFrame(columns=yearsofanalysis)
        for row in range(0, total_rows):
            df_summary.loc[sumtechs[row]] = "Nan"

        pop_future = specs_data.iloc[0][SPE_POP_FUTURE]
        urban_future = specs_data.iloc[0][SPE_URBAN_FUTURE]
        onsseter.project_pop_and_urban(pop_future, urban_future, base_year, yearsofanalysis)

        tier_index = scenario_info.iloc[scenario]['Target_electricity_consumption_level']
        prio_index = scenario_info.iloc[scenario]['Prioritization_algorithm']

        rural_tier = scenario_parameters.iloc[tier_index]['RuralTargetTier']
        urban_tier = scenario_parameters.iloc[tier_index]['UrbanTargetTier']

        prioritization = scenario_parameters.iloc[prio_index]['PrioritizationAlgorithm']
        auto_intensification = scenario_parameters.iloc[prio_index]['AutoIntensificationKM']

        pv_capital_cost_adjust = 1
        productive_demand = 1

        country_id = specs_data.iloc[0]['CountryCode']

        settlements_out_csv = os.path.join(results_folder, '{}-1-{}_{}.csv'.format(country_id, grid_option, tier_index))
        summary_csv = os.path.join(summary_folder, '{}-1-{}_{}_summary.csv'.format(country_id, grid_option, tier_index))

        onsseter.current_mv_line_dist()

        for year in yearsofanalysis:
            time_step = time_steps[year]
            start_year = year - time_step

            eleclimit = specs_data.loc[year]['ElecTarget']
            annual_new_grid_connections_limit = specs_data.loc[year, 'GridConnectionsLimitThousands'] * 1000
            annual_grid_cap_gen_limit = specs_data.loc[year, 'NewGridGenerationCapacityAnnualLimitMW'] * 1000
            grid_price = specs_data.loc[year, 'GridGenerationCost']
            diesel_price = specs_data.loc[year, 'DieselPrice']

            num_people_per_hh_rural = float(specs_data.iloc[0][SPE_NUM_PEOPLE_PER_HH_RURAL])
            num_people_per_hh_urban = float(specs_data.iloc[0][SPE_NUM_PEOPLE_PER_HH_URBAN])
            max_grid_extension_dist = float(specs_data.iloc[0][SPE_MAX_GRID_EXTENSION_DIST])

            # RUN_PARAM: Fill in general and technology specific parameters (e.g. discount rate, losses etc.)
            Technology.set_default_values(base_year=base_year,
                                          start_year=start_year,
                                          end_year=end_year)

            grid_calc = Technology(om_of_td_lines=0.02,
                                   distribution_losses=float(specs_data.iloc[0][SPE_GRID_LOSSES]),
                                   connection_cost_per_hh=125,
                                   base_to_peak_load_ratio=0.8,
                                   capacity_factor=1,
                                   tech_life=30,
                                   grid_capacity_investment=float(specs_data.iloc[0][SPE_GRID_CAPACITY_INVESTMENT]),
                                   grid_penalty_ratio=1,
                                   grid_price=grid_price,
                                   discount_rate=0.155)

            mg_hydro_calc = Technology(om_of_td_lines=0.02,
                                       distribution_losses=0.05,
                                       connection_cost_per_hh=100,
                                       base_to_peak_load_ratio=0.85,
                                       capacity_factor=0.5,
                                       tech_life=30,
                                       capital_cost={float("inf"): 3000},
                                       om_costs=0.03,
                                       mini_grid=True,
                                       discount_rate=0.198)

            mg_wind_calc = Technology(om_of_td_lines=0.02,
                                      distribution_losses=0.05,
                                      connection_cost_per_hh=100,
                                      base_to_peak_load_ratio=0.85,
                                      capital_cost={float("inf"): 3750},
                                      om_costs=0.02,
                                      tech_life=20,
                                      mini_grid=True,
                                      discount_rate=0.198)

            mg_pv_calc = Technology(om_of_td_lines=0.02,
                                    distribution_losses=0.05,
                                    connection_cost_per_hh=100,
                                    base_to_peak_load_ratio=0.85,
                                    tech_life=20,
                                    om_costs=0.015,
                                    capital_cost={float("inf"): 2950},
                                    mini_grid=True,
                                    discount_rate=0.198)

            sa_pv_calc = Technology(base_to_peak_load_ratio=0.9,
                                    tech_life=15,
                                    om_costs=0.02,
                                    capital_cost={float("inf"): 2600,
                                                  1: 2600,
                                                  0.100: 2600,
                                                  0.050: 2200,
                                                  0.020: 9200
                                                  },
                                    standalone=True,
                                    discount_rate=0.180)

            mg_diesel_calc = Technology(om_of_td_lines=0.02,
                                        distribution_losses=0.05,
                                        connection_cost_per_hh=100,
                                        base_to_peak_load_ratio=0.85,
                                        capacity_factor=0.7,
                                        tech_life=15,
                                        om_costs=0.1,
                                        capital_cost={float("inf"): 721},
                                        mini_grid=True,
                                        discount_rate=0.198)

            sa_diesel_calc = Technology(base_to_peak_load_ratio=0.9,
                                        capacity_factor=0.5,
                                        tech_life=10,
                                        om_costs=0.1,
                                        capital_cost={float("inf"): 938},
                                        standalone=True,
                                        discount_rate=0.180)

            mg_pv_hybrid_calc = Technology(om_of_td_lines=0.02,
                                           distribution_losses=0.05,
                                           connection_cost_per_hh=20,
                                           capacity_factor=0.5,
                                           tech_life=30,
                                           mini_grid=True,
                                           hybrid=True,
                                           discount_rate=0.198)

            mg_wind_hybrid_calc = Technology(om_of_td_lines=0.02,
                                             distribution_losses=0.05,
                                             connection_cost_per_hh=20,
                                             capacity_factor=0.5,
                                             tech_life=30,
                                             mini_grid=True,
                                             hybrid=True,
                                             discount_rate=0.198)

            sa_diesel_cost = {'diesel_price': diesel_price,
                              'efficiency': 0.28,
                              'diesel_truck_consumption': 14,
                              'diesel_truck_volume': 300}

            mg_diesel_cost = {'diesel_price': diesel_price,
                              'efficiency': 0.33,
                              'diesel_truck_consumption': 33.7,
                              'diesel_truck_volume': 15000}

            grid_cap_gen_limit = time_step * annual_grid_cap_gen_limit
            grid_connect_limit = time_step * annual_new_grid_connections_limit

            onsseter.set_scenario_variables(year, num_people_per_hh_rural, num_people_per_hh_urban, time_step,
                                            start_year, urban_tier, rural_tier, base_year)

            onsseter.diesel_cost_columns(sa_diesel_cost, mg_diesel_cost, year)

            mg_wind_hybrid_investment, mg_wind_hybrid_capacity = onsseter.calculate_wind_hybrids_lcoe(year,
                                                                                                      year - time_step,
                                                                                                      end_year,
                                                                                                      time_step,
                                                                                                      mg_wind_hybrid_calc)

            mg_pv_hybrid_investment, mg_pv_hybrid_capacity, mg_pv_investment = \
                onsseter.calculate_pv_hybrids_lcoe(year, year - time_step, end_year, time_step, mg_pv_hybrid_calc,
                                                   pv_capital_cost_adjust, 1500, 240)

            sa_diesel_investment, sa_diesel_capacity, sa_pv_investment, sa_pv_capacity, mg_diesel_investment, \
            mg_diesel_capacity, mg_pv_investment, mg_pv_capacity, mg_wind_investment, mg_wind_capacity, \
            mg_hydro_investment, mg_hydro_capacity = onsseter.calculate_off_grid_lcoes(mg_hydro_calc, mg_wind_calc, mg_pv_calc,
                                                                        sa_pv_calc, mg_diesel_calc,
                                                                        sa_diesel_calc, year, end_year, time_step,
                                                                        techs, tech_codes)

            grid_investment, grid_capacity, grid_cap_gen_limit, grid_connect_limit = \
                onsseter.pre_electrification(grid_price, year, time_step, end_year, grid_calc, grid_cap_gen_limit,
                                             grid_connect_limit)

            onsseter.df[SET_LCOE_GRID + "{}".format(year)], onsseter.df[SET_MIN_GRID_DIST + "{}".format(year)], \
            onsseter.df[SET_ELEC_ORDER + "{}".format(year)], onsseter.df[SET_MV_CONNECT_DIST], grid_investment,\
                grid_capacity = \
                onsseter.elec_extension(grid_calc,
                                        max_grid_extension_dist,
                                        year,
                                        start_year,
                                        end_year,
                                        time_step,
                                        grid_cap_gen_limit,
                                        grid_connect_limit,
                                        auto_intensification=auto_intensification,
                                        prioritization=prioritization,
                                        new_investment=grid_investment,
                                        new_capacity=grid_capacity)

            onsseter.df[SET_ELEC_ORDER] = onsseter.df[SET_ELEC_ORDER + "{}".format(year)]

            onsseter.results_columns(techs, tech_codes, year, time_step, prioritization, auto_intensification)

            onsseter.calculate_investments_and_capacity(sa_diesel_investment, sa_diesel_capacity, sa_pv_investment,
                                                        sa_pv_capacity, mg_diesel_investment, mg_diesel_capacity,
                                                        mg_pv_investment, mg_pv_capacity, mg_wind_investment,
                                                        mg_wind_capacity, mg_hydro_investment, mg_hydro_capacity,
                                                        mg_pv_hybrid_investment, mg_pv_hybrid_capacity,
                                                        mg_wind_hybrid_investment, mg_wind_hybrid_capacity,
                                                        grid_investment, grid_capacity, year)

            onsseter.apply_limitations(eleclimit, year, time_step, prioritization, auto_intensification)

            onsseter.calc_summaries(df_summary, sumtechs, tech_codes, year, time_step, yearsofanalysis[-1], transmission_investment, yearsofanalysis)

        for i in range(len(onsseter.df.columns)):
            if onsseter.df.iloc[:, i].dtype == 'float64':
                onsseter.df[onsseter.df.columns[i]] = pd.to_numeric(onsseter.df[onsseter.df.columns[i]], downcast='float')
                # onsseter.df.iloc[:, i] = pd.to_numeric(onsseter.df.iloc[:, i], downcast='float')
            elif onsseter.df.iloc[:, i].dtype == 'int64':
                onsseter.df[onsseter.df.columns[i]] = pd.to_numeric(onsseter.df[onsseter.df.columns[i]], downcast='signed')
                # onsseter.df.iloc[:, i] = pd.to_numeric(onsseter.df.iloc[:, i], downcast='signed')

        df_summary.to_csv(summary_csv, index=sumtechs)
        onsseter.df.to_csv(settlements_out_csv, index=False)

        logging.info('Finished')
