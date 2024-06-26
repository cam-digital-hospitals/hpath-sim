"""Compute KPIs for a model from simulation results."""
from typing import TYPE_CHECKING, Iterable
from typing_extensions import TypedDict

import numpy as np
import pandas as pd
import pydantic as pyd
import salabim as sim

from . import util
from .chart_datatypes import ChartData, MultiChartData

if TYPE_CHECKING:
    from .model import Model

# TODO: create confidence-interval versions of the below KPI functions


def wip_hourly(wip: sim.Monitor) -> pd.DataFrame:
    """Return a dataframe showing the hourly mean WIP
    of a histopath stage."""
    df = pd.DataFrame(wip.tx())\
        .T\
        .rename(columns={0: 't', 1: wip.name()})\
        .set_index('t')
    df.index = pd.to_timedelta(df.index, 'h')

    df1 = df.resample('h').mean()
    df1.index /= pd.Timedelta(1, unit='h')

    # handle hour intervals with no WIP changes
    df2 = df.resample('h').ffill()
    df2.index /= pd.Timedelta(1, unit='h')
    return df1.fillna(df2)


def wip_hourlies(mdl: 'Model') -> pd.DataFrame:
    """Return a dataframe showing the hourly mean WIP
    for each stage in the histopathology process."""
    return pd.concat([wip_hourly(wip) for wip in util.dc_values(mdl.wips)], axis='columns')


def wip_summary(mdl: 'Model') -> pd.DataFrame:
    """Return a dataframe with the histopath stages as rows, and
    the mean WIP of each stage as its "mean" column."""
    df = pd.DataFrame({wip.name(): [wip.mean()] for wip in util.dc_values(mdl.wips)})
    df.index = ['mean']
    return df.T


def _timestamp_helper(mdl: 'Model') -> pd.DataFrame:
    # Actually contains more data than just timestamps but we will ignore those columns
    timestamps = pd.DataFrame.from_dict(
        {
            # Only keep non-bootstrap specimens that have completed service
            k: v for k, v in mdl.specimen_data.items() if 'init' not in k and 'report_end' in v
        },
        orient='index'
    )

    # specimen.123 -> 123
    timestamps.index = [int(idx.rsplit('.', 1)[1]) for idx in timestamps.index]
    return timestamps


def overall_tat(mdl: 'Model') -> pd.DataFrame:
    """Overall mean turnaround time."""
    timestamps = _timestamp_helper(mdl)
    # Extract TAT from data columns
    tat_total = timestamps['report_end'] - timestamps['reception_start']
    return tat_total.mean()


def overall_lab_tat(mdl: 'Model') -> pd.DataFrame:
    """Overall mean turnaround time."""
    timestamps = _timestamp_helper(mdl)
    # Extract TAT from data columns
    tat_lab = timestamps['qc_end'] - timestamps['reception_start']
    return tat_lab.mean()


def tat_by_stage(mdl: 'Model') -> pd.DataFrame:
    """Return a dataframe with the histopath stages as rows, and
    the mean turnaround time of each stage as its "mean (hours)" column."""
    timestamps = _timestamp_helper(mdl)

    stages = [x.rsplit('_end', 1)[0] for x in timestamps.columns if x.endswith('_end')]
    df = pd.concat([timestamps[f'{x}_end'] - timestamps[f'{x}_start']
                    for x in stages], axis='columns')
    df.columns = stages

    ret = pd.DataFrame({'mean (hours)': df.mean()})
    ret.index = [wip.name() for wip in
                 util.dc_values(mdl.wips)][1:]  # Remove 'Total' to match ret data
    return ret


def tat_dist(mdl: 'Model', day_list: Iterable[int]) -> pd.DataFrame:
    """Return a dataframe showing the proportion of specimens
    completed within ``n`` days, for ``n`` in ``day_list``. Both
    overall and lab turnaround time are shown."""

    # Actually contains more data than just timestamps but we will ignore those columns
    timestamps = _timestamp_helper(mdl)

    # Extract TAT from data columns
    tat_total = timestamps['report_end'] - timestamps['reception_start']
    tat_lab = timestamps['qc_end'] - timestamps['reception_start']

    return pd.DataFrame([{
        'days': days,
        'TAT': np.mean(tat_total <= days*24),
        'TAT_lab': np.mean(tat_lab <= days*24)
    } for days in day_list]).set_index('days')


def utilisation_means(mdl: 'Model') -> pd.DataFrame:
    """Return a dataframe showing the mean utilisation of each resource."""
    ret = {r.name(): r.claimed_quantity.mean()/r.capacity.mean()
           for r in util.dc_values(mdl.resources)}
    return pd.DataFrame({'mean': ret})


def q_length_means(mdl: 'Model') -> pd.DataFrame:
    """Return a dataframe showing the mean queue length of each resource."""
    ret = {r.name(): r.requesters().length.mean()/r.capacity.mean()
           for r in util.dc_values(mdl.resources)}
    return pd.DataFrame({'mean': ret})


def allocation_timeseries(res: sim.Resource) -> pd.DataFrame:
    """Return a dataframe showing the allocation level of a resource."""
    df = pd.DataFrame(res.capacity.tx())\
        .T\
        .rename(columns={0: 't', 1: res.name()})\
        .set_index('t')
    # Duplicates can happen as the final allocation change may be at the
    # simulation end time.  Remove these.
    return df.groupby('t').tail(1)


def utilisation_hourly(res: sim.Resource) -> pd.DataFrame:
    """Return a dataframe showing the hourly mean utilisation of a resource."""
    df = pd.DataFrame(res.claimed_quantity.tx())\
        .T\
        .rename(columns={0: 't', 1: res.name()})\
        .set_index('t')
    df.index = pd.to_timedelta(df.index, unit='h')
    df1 = df.resample('h').mean()
    df1.index /= pd.Timedelta(1, unit='h')

    # handle hour intervals with no utilisation changes
    df2 = df.resample('h').ffill()
    df2.index /= pd.Timedelta(1, unit='h')
    return df1.fillna(df2)


def utilisation_hourlies(mdl: 'Model') -> pd.DataFrame:
    """Return a dataframe showing the hourly mean utilisation of each resource."""
    return pd.concat(
        [utilisation_hourly(res) for res in util.dc_values(mdl.resources)],
        axis='columns'
    )


def q_length_hourly(res: sim.Resource) -> pd.DataFrame:
    """Return a dataframe showing the hourly mean queue length for a resource.
    Queue members can be specimen, block, slide, or batch tasks including delivery."""
    df = pd.DataFrame(res.requesters().length.tx())\
        .T\
        .rename(columns={0: 't', 1: res.name()})\
        .set_index('t')
    df.index = pd.to_timedelta(df.index, unit='h')
    df1 = df.resample('h').mean()
    df1.index /= pd.Timedelta(1, unit='h')

    # handle hour intervals with no queue changes
    df2 = df.resample('h').ffill()
    df2.index /= pd.Timedelta(1, unit='h')
    return df1.fillna(df2)


def q_length_hourlies(mdl: 'Model') -> pd.DataFrame:
    """Return a dataframe showing the hourly mean queue length of each resource.
    Queue members can be specimen, block, slide, or batch tasks including delivery."""
    return pd.concat(
        [utilisation_hourly(res) for res in util.dc_values(mdl.resources)],
        axis='columns'
    )


Progress = TypedDict('Progress', {
    '7': float,
    '10': float,
    '12': float,
    '21': float
})
"""Returns the proportion of specimens completed within 7, 10, 12, and 21 days."""

LabProgress = TypedDict('LabProgress', {
    '3': float
})
"""Returns the proportion of specimens with lab component completed within three days."""


class Report(pyd.BaseModel):
    """Dataclass for reporting a set of KPIs for passing to a frontend visualisation server.
    In the current implementation, this is https://github.com/lakeesiv/digital-twin"""
    overall_tat: float
    lab_tat: float
    progress: Progress
    lab_progress: LabProgress
    tat_by_stage: ChartData
    resource_allocation: dict[str, ChartData]  # ChartData for each resource
    wip_by_stage: MultiChartData
    utilization_by_resource: ChartData
    q_length_by_resource: ChartData
    hourly_utilization_by_resource: MultiChartData

    overall_tat_min: float | None = pyd.Field(default=None)
    overall_tat_max: float | None = pyd.Field(default=None)
    lab_tat_min: float | None = pyd.Field(default=None)
    lab_tat_max: float | None = pyd.Field(default=None)
    progress_min: Progress | None = pyd.Field(default=None)
    progress_max: Progress | None = pyd.Field(default=None)
    lab_progress_min: LabProgress | None = pyd.Field(default=None)
    lab_progress_max: LabProgress | None = pyd.Field(default=None)

    @staticmethod
    def from_model(mdl: 'Model') -> 'Report':
        """Produce a single dataclass for passing simulation results to a frontend server."""
        return __class__(
            overall_tat=overall_tat(mdl),
            lab_tat=overall_lab_tat(mdl),
            progress=dict(zip(
                ['7', '10', '12', '21'],
                tat_dist(mdl, [7, 10, 12, 21]).TAT.tolist()
            )),
            lab_progress=dict(zip(['3'], tat_dist(mdl, [3]).TAT_lab.tolist())),
            tat_by_stage=ChartData.from_pandas(tat_by_stage(mdl)),
            resource_allocation={
                res.name(): ChartData.from_pandas(allocation_timeseries(res))
                for res in util.dc_values(mdl.resources)
            },
            wip_by_stage=MultiChartData.from_pandas(wip_hourlies(mdl)),
            utilization_by_resource=ChartData.from_pandas(utilisation_means(mdl)),
            q_length_by_resource=ChartData.from_pandas(q_length_means(mdl)),
            hourly_utilization_by_resource=MultiChartData.from_pandas(
                utilisation_hourlies(mdl))
        )


def multi_mean_tats(all_results: dict[int, dict]) -> ChartData:
    """Chart data for bar chart of overall mean TATs by scenario.

    TODO: Change to grouped bar chart with both overall and lab TAT?
    Does the front-end support this?
    """
    ret = {}
    ret['x'] = [str(scenario_id) for scenario_id in all_results.keys()]
    ret['y'] = [result['overall_tat'] for result in all_results.values()]
    return ret


def multi_mean_util(all_results: dict[int, dict]) -> dict[str, ChartData]:
    """Get mean resource utilisation values from a multi-scenario analysis result list.
    Each resource in the model maps to one barchart, with scenarios as x axis"""
    ret = {}
    kpi = 'utilization_by_resource'

    scenario_ids = list(all_results.keys())
    resources = all_results[scenario_ids[0]][kpi]['x']  # list of resources
    for idx, resource in enumerate(resources):
        chart_data = {}

        # Change scenario_ids to strings for categorical data
        chart_data['x'] = [str(scenario_id) for scenario_id in scenario_ids]

        chart_data['y'] = [result[kpi]['y'][idx] for result in all_results.values()]
        ret[resource] = chart_data

    return ret


def multi_util_hourlies(all_results: dict[int, dict]) -> dict[str, MultiChartData]:
    """Get mean resource utilisation values from a multi-scenario analysis result list.
    Each resource in the model maps to one barchart, with scenarios as line labels."""
    ret = {}
    kpi = 'hourly_utilization_by_resource'

    scenario_ids = list(all_results.keys())

    # These should be the same for all scenarios in an analysis, so just read the first one,
    # i.e. scenario_ids[0]
    resources = all_results[scenario_ids[0]][kpi]['labels']  # list of resources
    hour_series = all_results[scenario_ids[0]][kpi]['x']  # 1...sim_length

    for idx, resource in enumerate(resources):
        chart_data = {}

        # We assume all results for this KPI have the same x data across all scenarios
        chart_data['x'] = hour_series
        chart_data['labels'] = [str(scenario_id) for scenario_id in scenario_ids]
        chart_data['y'] = [result[kpi]['y'][idx] for result in all_results.values()]
        ret[resource] = chart_data
    return ret
