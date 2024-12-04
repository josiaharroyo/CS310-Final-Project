import pandas as pd
import requests
import boto3
import xml.etree.ElementTree as ET
from datetime import datetime
from geopy.distance import geodesic
from sagemaker.predictor import Predictor

# Constants
API_KEY = "5e23a507898a45bb83c1b91b24263d71"
BASE_URL = "http://lapi.transitchicago.com/api/1.0/ttarrivals.aspx"
DYNAMODB_TABLE = "UserHomeStops"
REGION = "us-east-2"

# DynamoDB Client
dynamodb = boto3.resource('dynamodb', region_name=REGION)

# Attach to the SageMaker endpoint
endpoint_name = "cta-ridership-predictor"  # Use the exact name of your endpoint
xgboost_predictor = Predictor(endpoint_name=endpoint_name)

# Load Station Data
def load_station_data(file_path):
    df = pd.read_csv(file_path)
    return df[['STATION_NAME', 'MAP_ID', 'Location']].drop_duplicates()

# Option 1: View All Stations
def view_stations(station_data):
    print("\nStation List:")
    print(station_data.to_string(index=False))

# Option 2: Set Home Location
def set_home_location(user_id, station_data):
    station_name = input("Enter your home station name (e.g., 'Foster'): ")
    station_info = station_data[station_data['STATION_NAME'].str.contains(station_name, case=False, na=False)]
    if station_info.empty:
        print(f"Station '{station_name}' not found.")
        return
    selected_station = station_info.iloc[0]
    map_id = selected_station['MAP_ID']
    save_home_location(user_id, station_name, map_id)
    print(f"Home location set to '{station_name}'.")

def save_home_location(user_id, home_stop, map_id):
    table = dynamodb.Table(DYNAMODB_TABLE)
    table.put_item(Item={
        "user_id": user_id,
        "home_stop": home_stop,
        "map_id": str(map_id)
    })

# Option 3: Search Station
def search_station():
    station_id = input("Enter the station MAP_ID: ")
    try:
        xml_data = fetch_train_arrivals(station_id)
        arrivals = parse_train_arrivals_with_direction(xml_data)
        display_arrivals_with_direction(arrivals)
    except Exception as e:
        print(f"An error occurred: {e}")

def parse_train_arrivals_with_direction(xml_data):
    root = ET.fromstring(xml_data)
    arrivals = []
    for eta in root.findall("./eta"):
        station = eta.find("staNm").text
        destination = eta.find("destNm").text
        arrival_time = eta.find("arrT").text
        direction = eta.find("trDr").text  # Direction (1 for North, 5 for South, etc.)
        status = "Approaching" if eta.find("isApp").text == "1" else "Scheduled"

        # Calculate countdown in minutes
        current_time = datetime.now()
        arrival_dt = datetime.strptime(arrival_time, "%Y%m%d %H:%M:%S")
        minutes_to_arrival = (arrival_dt - current_time).total_seconds() // 60

        if minutes_to_arrival < 0:
            continue

        arrivals.append({
            "station": station,
            "destination": destination,
            "direction": direction,
            "minutes_to_arrival": int(minutes_to_arrival),
            "status": status,
        })
    return arrivals

def display_arrivals_with_direction(arrivals):
    direction_mapping = {"1": "North", "5": "South"}  # Example mapping; extend as needed
    print("\nUpcoming Trains:")
    for train in sorted(arrivals, key=lambda x: x["minutes_to_arrival"])[:5]:
        direction = direction_mapping.get(train["direction"], "Unknown")
        print(f"To {train['destination']} ({direction}) in {train['minutes_to_arrival']} minutes ({train['status']}).")


# Fetch Train Arrivals
def fetch_train_arrivals(mapid):
    url = f"{BASE_URL}?key={API_KEY}&mapid={mapid}"
    response = requests.get(url)
    if response.status_code != 200:
        raise Exception(f"Error fetching data: {response.status_code}")
    return response.content

# Parse Train Arrivals
def parse_train_arrivals(xml_data):
    root = ET.fromstring(xml_data)
    arrivals = []
    for eta in root.findall("./eta"):
        station = eta.find("staNm").text
        destination = eta.find("destNm").text
        arrival_time = eta.find("arrT").text
        status = "Approaching" if eta.find("isApp").text == "1" else "Scheduled"

        # Calculate countdown in minutes
        current_time = datetime.now()
        arrival_dt = datetime.strptime(arrival_time, "%Y%m%d %H:%M:%S")
        minutes_to_arrival = (arrival_dt - current_time).total_seconds() // 60

        if minutes_to_arrival < 0:
            continue

        arrivals.append({
            "station": station,
            "destination": destination,
            "minutes_to_arrival": int(minutes_to_arrival),
            "status": status,
        })
    return arrivals

def display_arrivals(arrivals):
    print("\nUpcoming Trains:")
    for train in sorted(arrivals, key=lambda x: x["minutes_to_arrival"])[:5]:
        print(f"To {train['destination']} in {train['minutes_to_arrival']} minutes ({train['status']}).")


def search_with_distance(user_id, station_data):
    # Fetch home location from DynamoDB
    home = fetch_home_location(user_id)
    if not home:
        print("Home location not set. Please set a home location first.")
        return

    # Find home station details
    home_station = station_data[station_data["MAP_ID"] == int(home["map_id"])]
    if home_station.empty:
        print("Home station details not found in station data.")
        return

    home_coords = tuple(map(float, home_station.iloc[0]["Location"].strip("()").split(", ")))

    # Get target station input
    station_id = input("Enter the station MAP_ID to calculate distance to home: ")
    target_station = station_data[station_data["MAP_ID"] == int(station_id)]
    if target_station.empty:
        print(f"Station with MAP_ID {station_id} not found.")
        return

    # Extract target station coordinates
    target_coords = tuple(map(float, target_station.iloc[0]["Location"].strip("()").split(", ")))

    # Calculate distance
    distance = geodesic(home_coords, target_coords).miles
    print(f"The distance between '{home['home_stop']}' and '{target_station.iloc[0]['STATION_NAME']}' is approximately {distance:.2f} miles.")

    # Optionally, display train arrivals for the target station
    view_trains = input("Do you want to view train arrivals for this station? (yes/no): ").strip().lower()
    if view_trains == "yes":
        try:
            xml_data = fetch_train_arrivals(station_id)
            arrivals = parse_train_arrivals_with_direction(xml_data)
            display_arrivals_with_direction(arrivals)
        except Exception as e:
            print(f"An error occurred: {e}")


def fetch_home_location(user_id):
    table = dynamodb.Table(DYNAMODB_TABLE)
    response = table.get_item(Key={"user_id": user_id})
    return response.get("Item", None)



def estimate_crowdedness_and_wait_time(station_id, daytype_encoded, ridership_threshold=5000):
    """
    Estimate whether a station will be crowded and the expected wait time based on ridership data.
    
    Parameters:
    - station_id (int): The ID of the station.
    - daytype_encoded (int): Encoded day type (0=Weekday, 1=Saturday, 2=Sunday/Holiday).
    - ridership_threshold (int): Threshold for crowdedness (default: 5000).
    
    Returns:
    - dict: Contains crowdedness status and expected wait time.
    """
    try:
        # Predict ridership using SageMaker endpoint
        payload = f"{station_id},{daytype_encoded}"
        response = xgboost_predictor.predict(payload, initial_args={"ContentType": "text/csv"})
        predicted_rides = int(float(response.decode("utf-8")))

        # Determine crowdedness
        crowded = predicted_rides > ridership_threshold
        crowded_status = "Crowded" if crowded else "Not Crowded"

        # Estimate wait time
        # Assumes a base wait time and additional delay based on crowdedness
        base_wait_time = 5  # minutes
        additional_wait_time = (predicted_rides / ridership_threshold) * 5 if crowded else 0
        total_wait_time = base_wait_time + additional_wait_time

        return {
            "predicted_rides": predicted_rides,
            "crowded_status": crowded_status,
            "expected_wait_time": round(total_wait_time, 2),  # in minutes
        }

    except Exception as e:
        print(f"Error estimating crowdedness and wait time: {e}")
        return None

def ridership_prediction_with_crowdedness(station_data):
    station_name = input("Enter the station name (e.g., 'Foster'): ")
    station_info = station_data[station_data['STATION_NAME'].str.contains(station_name, case=False, na=False)]
    if station_info.empty:
        print(f"Station '{station_name}' not found.")
        return

    station_id = station_info.iloc[0]["MAP_ID"]

    daytype = input("Enter day type (W for Weekday, A for Saturday, U for Sunday/Holiday): ").strip().upper()
    daytype_mapping = {"W": 0, "A": 1, "U": 2}
    if daytype not in daytype_mapping:
        print("Invalid day type. Please enter W, A, or U.")
        return

    daytype_encoded = daytype_mapping[daytype]

    # Call the new estimation function
    results = estimate_crowdedness_and_wait_time(station_id, daytype_encoded)
    if results:
        print(f"\nEstimated Ridership for '{station_name}': {results['predicted_rides']} rides.")
        print(f"Crowdedness Status: {results['crowded_status']}")
        print(f"Expected Wait Time: {results['expected_wait_time']} minutes")


def ridership_prediction(station_data):
    

    station_name = input("Enter the station name (e.g., 'Foster'): ")
    station_info = station_data[station_data['STATION_NAME'].str.contains(station_name, case=False, na=False)]

    if station_info.empty:
        print(f"Station '{station_name}' not found.")
        return

    station_id = station_info.iloc[0]["MAP_ID"]

    daytype = input("Enter day type (W for Weekday, A for Saturday, U for Sunday/Holiday): ").strip().upper()
    daytype_mapping = {"W": 0, "A": 1, "U": 2}
    if daytype not in daytype_mapping:
        print("Invalid day type. Please enter W, A, or U.")
        return

    daytype_encoded = daytype_mapping[daytype]

    # Predict ridership
    try:
        payload = f"{station_id},{daytype_encoded}"
        response = xgboost_predictor.predict(
            payload,
            initial_args={"ContentType": "text/csv"}
        )
        predicted_rides = int(float(response.decode("utf-8")))
        print(f"Estimated ridership for '{station_name}' on the selected day: {predicted_rides} rides.")
    except Exception as e:
        print(f"Error predicting ridership: {e}")

# Main Menu
def main():
    file_path = "./CTA_-_System_Information_-_List_of__L__Stops_20241203.csv"
    station_data = load_station_data(file_path)
    user_id = "default_user"

    while True:
        print("\n--- CTA Train Tracker ---")
        print("1. View Stations")
        print("2. Set Home Location")
        print("3. Search Station")
        print("4. Search Station with Distance to Home")
        print("5. Predictions on Ridership (TODO)")
        print("6. Quit")
        choice = input("Enter your choice (1-6): ")

        if choice == "1":
            view_stations(station_data)
        elif choice == "2":
            set_home_location(user_id, station_data)
        elif choice == "3":
            search_station()
        elif choice == "4":
            search_with_distance(user_id, station_data)
        elif choice == "5":
            ridership_prediction_with_crowdedness(station_data)
        elif choice == "6":
            print("Exiting program. Goodbye!")
            break
        else:
            print("Invalid choice. Please enter a number between 1 and 6.")

if __name__ == "__main__":
    main()