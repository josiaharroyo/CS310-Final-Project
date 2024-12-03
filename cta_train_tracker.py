import pandas as pd
import requests
import xml.etree.ElementTree as ET
from datetime import datetime

#API Key and Base URL
API_KEY = "5e23a507898a45bb83c1b91b24263d71"
BASE_URL = "http://lapi.transitchicago.com/api/1.0/ttarrivals.aspx"

#Load station data from CSV
def load_station_data(file_path):
    df = pd.read_csv(file_path)
    return df[['STATION_NAME', 'MAP_ID']].drop_duplicates()

def fetch_train_arrivals(mapid):
    """Fetch train arrival data for a given station."""
    url = f"{BASE_URL}?key={API_KEY}&mapid={mapid}"
    response = requests.get(url)
    if response.status_code != 200:
        raise Exception(f"Error fetching data: {response.status_code}")
    return response.content

def parse_train_arrivals(xml_data):
    """Parse XML train arrival data and return as a list."""
    root = ET.fromstring(xml_data)
    arrivals = []
    
    for eta in root.findall("./eta"):
        station = eta.find("staNm").text
        platform = eta.find("stpDe").text
        route = eta.find("rt").text
        destination = eta.find("destNm").text
        arrival_time = eta.find("arrT").text
        status = "Approaching" if eta.find("isApp").text == "1" else "Scheduled"
        
        #Calculate countdown in minutes
        current_time = datetime.now()
        arrival_dt = datetime.strptime(arrival_time, "%Y%m%d %H:%M:%S")
        minutes_to_arrival = (arrival_dt - current_time).total_seconds() // 60
        
        #Ignore negative times
        if minutes_to_arrival < 0:
            continue
        
        #Determine inbound or outbound
        if "Loop" in destination or "Howard" in destination:
            direction = "Inbound"
        else:
            direction = "Outbound"
        
        arrivals.append({
            "route": route,
            "direction": direction,
            "destination": destination,
            "minutes_to_arrival": int(minutes_to_arrival),
            "status": status,
        })
    return arrivals

def display_arrivals(arrivals):
    """Filter to two soonest options per route/direction and display results."""
    print("\nUpcoming Trains:")

    #Group by route and direction, keeping only the two soonest arrivals
    grouped = {}
    for train in arrivals:
        key = (train['route'], train['direction'])
        if key not in grouped:
            grouped[key] = []
        grouped[key].append(train)

    for key, trains in grouped.items():
        #Sort by minutes_to_arrival and keep only the two soonest
        trains = sorted(trains, key=lambda x: x['minutes_to_arrival'])[:2]
        route, direction = key
        times = ", ".join(f"{train['minutes_to_arrival']} min" for train in trains)
        print(f"{route} Line\n{direction} to {trains[0]['destination']}: {times}")

def main():
    #Load the station data
    file_path = "CTA_-_System_Information_-_List_of__L__Stops_20241203.csv"
    station_data = load_station_data(file_path)
    
    #Prompt user for station name
    station_name = input("Enter your station name (e.g., 'Foster'): ")
    mapid_row = station_data[station_data['STATION_NAME'].str.contains(station_name, case=False, na=False)]
    
    if mapid_row.empty:
        print(f"Station '{station_name}' not found in the database.")
        return
    
    mapid = mapid_row['MAP_ID'].values[0]
    
    #Fetch and display train arrivals
    try:
        print(f"\nFetching arrival times for {station_name} station...")
        xml_data = fetch_train_arrivals(mapid)
        arrivals = parse_train_arrivals(xml_data)
        if arrivals:
            display_arrivals(arrivals)
        else:
            print("No trains arriving at the moment.")
    except Exception as e:
        print(f"An error occurred: {e}")

if __name__ == "__main__":
    main()
