"""JobPortal is for any job and any schooling. These check the rule filters that run before any AI sees a job: a real title
for someone's kind of work has to reach them, and a title from another line of work shouldn't. No network and no AI."""
import pytest

from jobportal.candidate import onboarding
from jobportal.core import config, genres, settings, textutil
from jobportal.search import pipeline
from jobportal.search.collectors.base import RawJob

# (the job they want, titles employers really use for it, a title from other work)
PEOPLE = [
    ("Registered Nurse", ["RN - Med Surg", "Staff Nurse", "Registered Nurse, ICU", "Travel RN"], "Software Engineer"),
    ("Certified Nursing Assistant", ["CNA", "Nursing Assistant", "Nurse Aide - Nights"], "Accountant"),
    ("Dental Hygienist", ["Registered Dental Hygienist", "Hygienist"], "Welder"),
    ("Phlebotomist", ["Phlebotomy Technician", "Phlebotomist I"], "Cook"),
    ("Pharmacy Technician", ["Certified Pharmacy Tech", "Pharmacy Technician"], "Roofer"),
    ("Home Health Aide", ["HHA", "Home Care Aide", "Caregiver"], "Data Scientist"),
    ("Electrician", ["Journeyman Electrician", "Electrician Apprentice", "Industrial Electrician"], "Paralegal"),
    ("Plumber", ["Service Plumber", "Plumbing Technician", "Journeyman Plumber"], "Barista"),
    ("Welder", ["MIG Welder", "Welder/Fabricator", "Pipe Welder"], "Teacher"),
    ("HVAC Technician", ["HVAC Installer", "HVAC Service Tech", "Heating and Cooling Technician"], "Nurse"),
    ("Carpenter", ["Finish Carpenter", "Framing Carpenter", "Carpenter Helper"], "Analyst"),
    ("Truck Driver", ["CDL A Driver", "OTR Truck Driver", "Class A CDL Driver", "Delivery Driver"], "Nurse"),
    ("Forklift Operator", ["Forklift Driver", "Warehouse Associate - Forklift", "Material Handler"], "Attorney"),
    ("Warehouse Associate", ["Warehouse Worker", "Picker Packer", "Order Picker"], "Dentist"),
    ("Line Cook", ["Cook", "Prep Cook", "Line Cook - Nights", "Kitchen Staff"], "Engineer"),
    ("Server", ["Restaurant Server", "Waitstaff", "Banquet Server"], "Mechanic"),
    ("Bartender", ["Lead Bartender", "Bar Staff"], "Teacher"),
    ("Barista", ["Coffee Barista", "Shift Supervisor - Barista"], "Plumber"),
    ("Hair Stylist", ["Hairstylist", "Salon Stylist", "Cosmetologist"], "Driver"),
    ("Cashier", ["Front End Cashier", "Retail Cashier", "Sales Associate"], "Scientist"),
    ("Retail Store Manager", ["Assistant Store Manager", "Store Manager"], "Welder"),
    ("Elementary School Teacher", ["3rd Grade Teacher", "Teacher - Elementary", "Grade 2 Teacher"], "Electrician"),
    ("Substitute Teacher", ["Sub Teacher", "Substitute - K12", "Guest Teacher"], "Cook"),
    ("Preschool Teacher", ["Early Childhood Educator", "Pre-K Teacher", "Daycare Teacher"], "Accountant"),
    ("Paraprofessional", ["Paraeducator", "Teacher Aide", "Instructional Aide"], "Machinist"),
    ("Professor", ["Assistant Professor of Biology", "Adjunct Instructor", "Lecturer"], "Roofer"),
    ("Librarian", ["Reference Librarian", "Library Assistant", "Youth Services Librarian"], "Trucker"),
    ("Paralegal", ["Litigation Paralegal", "Legal Assistant"], "Cook"),
    ("Attorney", ["Associate Attorney", "Staff Attorney", "Lawyer"], "Nurse"),
    ("Accountant", ["Staff Accountant", "Senior Accountant", "CPA"], "Welder"),
    ("Bookkeeper", ["Full Charge Bookkeeper", "Accounts Payable Clerk"], "Nurse"),
    ("Bank Teller", ["Teller", "Universal Banker"], "Machinist"),
    ("Insurance Agent", ["Licensed Insurance Agent", "Insurance Sales Agent"], "Electrician"),
    ("Real Estate Agent", ["Realtor", "Leasing Agent", "Licensed Real Estate Salesperson"], "Cook"),
    ("Customer Service Representative", ["Call Center Agent", "CSR", "Customer Support Specialist"], "Roofer"),
    ("Administrative Assistant", ["Office Assistant", "Executive Assistant", "Receptionist", "Secretary"], "Mechanic"),
    ("Police Officer", ["Patrol Officer", "Deputy Sheriff", "Police Recruit"], "Barista"),
    ("Firefighter", ["Firefighter/EMT", "Paramedic Firefighter"], "Paralegal"),
    ("EMT", ["Emergency Medical Technician", "Paramedic", "EMT-Basic"], "Accountant"),
    ("Security Guard", ["Security Officer", "Armed Guard", "Loss Prevention Officer"], "Pharmacist"),
    ("Farm Worker", ["Farmhand", "Harvest Crew", "Agricultural Worker", "Ranch Hand"], "Attorney"),
    ("Landscaper", ["Landscape Laborer", "Groundskeeper", "Lawn Care Technician"], "Teacher"),
    ("Housekeeper", ["Room Attendant", "Hotel Housekeeper", "Janitor", "Custodian"], "Developer"),
    ("Auto Mechanic", ["Automotive Technician", "Diesel Mechanic", "Lube Tech"], "Librarian"),
    ("Machinist", ["CNC Machinist", "CNC Operator", "Tool and Die Maker"], "Nurse"),
    ("Graphic Designer", ["Visual Designer", "Production Artist"], "Plumber"),
    ("Photographer", ["Staff Photographer", "Portrait Photographer"], "Welder"),
    ("Actor", ["Performer", "Theater Actor", "Stage Actor"], "Accountant"),
    ("Musician", ["Church Organist", "Music Director", "Session Musician"], "Plumber"),
    ("Journalist", ["Staff Reporter", "News Reporter", "Copy Editor"], "Cook"),
    ("Social Worker", ["LCSW", "Case Manager", "Licensed Social Worker"], "Machinist"),
    ("Veterinary Technician", ["Vet Tech", "Veterinary Assistant"], "Roofer"),
    ("Pastor", ["Associate Pastor", "Youth Minister", "Worship Leader"], "Electrician"),
    ("Pilot", ["First Officer", "Commercial Pilot"], "Dentist"),
    ("Flight Attendant", ["Cabin Crew"], "Plumber"),
    ("Software Engineer", ["Backend Developer", "Full Stack Engineer", "SWE II"], "Line Cook"),
]


@pytest.mark.parametrize("target, titles, other", PEOPLE, ids=[p[0] for p in PEOPLE])
def test_their_jobs_reach_them_and_others_dont(target, titles, other):
    matcher = textutil.TargetMatcher([target])
    assert genres.classify(target), f"no kind of work for {target}"
    assert [t for t in titles if not matcher.matches(t)] == []
    assert not matcher.matches(other)


@pytest.mark.parametrize("target, title", [("Line Cook", "Electrical Line Worker"), ("Line Cook", "Line Tech"), ("Home Health Aide", "Home Depot Cashier")])
def test_a_word_that_only_describes_the_job_doesnt_count(target, title):
    assert not textutil.TargetMatcher([target]).matches(title)


def job(title: str) -> RawJob:
    return RawJob(source="ats", title=title, company="Example Co", url="https://jobs.example.com/1", location="Columbus, OH")


def early_career_filters(target: str) -> pipeline.RuleFilters:
    """The rule filters of someone looking for their first job."""
    cfg = settings.get()
    cfg["search"]["levels"] = ["entry"]
    cfg["filters"]["title_include"], cfg["filters"]["title_exclude"] = config.title_filters(["entry"], [target])
    cfg["locations"]["allowed"] = ["Columbus, OH"]
    filters = pipeline.RuleFilters(cfg)
    filters.targets = textutil.TargetMatcher([target])
    return filters


@pytest.mark.parametrize("target, title", [("Home Health Aide", "Caregiver"), ("Line Cook", "Kitchen Staff"), ("Welder", "Pipe Welder"),
                                           ("Farm Worker", "Farmhand"), ("Paraprofessional", "Teacher Aide")])
def test_a_first_job_seeker_keeps_titles_that_never_name_a_level(target, title):
    passed, why, _ = early_career_filters(target).check(job(title))
    assert passed, why


def test_a_level_still_counts_where_titles_name_it():
    passed, why, _ = early_career_filters("Software Engineer Intern").check(job("Principal Software Engineer"))
    assert not passed and "level" in why or "senior" in why


def test_any_schooling_can_be_picked():
    education = {key for key, _ in onboarding.FIELDS["education_level"]["options"]}
    assert {"none", "some_high_school", "high_school", "trade", "apprenticeship", "military", "bachelor", "doctorate"} <= education
    assert not onboarding.FIELDS["education_level"].get("required") and not onboarding.FIELDS["school"].get("required")
