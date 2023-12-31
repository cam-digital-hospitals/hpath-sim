"""Module containing the main simulation entry point for histopathology model
configurations."""
from .config import Config
from .kpis import Report
from .model import Model
from . import db


def simulate(config: Config, scenario_id: int):
    """Run a simulation and update the hpath simulation database."""
    print(f"SIM: id={scenario_id}, sim_hours={config.sim_hours}")
    model = Model(config)
    model.run()
    report_json = Report.from_model(model).model_dump_json()
    db.update_progress(scenario_id)
    db.save_result(scenario_id, report_json)
