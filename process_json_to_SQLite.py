import datetime
import json
import logging

from peewee import CharField, DateTimeField, Model, SqliteDatabase, TextField
from playhouse.shortcuts import model_to_dict

# Define the SQLite database
db = SqliteDatabase("rulings.db")


# Define the model for the rulings, matching the schema in assets/rulings_schema.json
class Ruling(Model):
    card_name = CharField()
    type = CharField()
    text = TextField()
    source_updated = DateTimeField(null=True)
    source_type = CharField(null=True)
    source_version = CharField(null=True)

    class Meta:
        database = db


# Connect to the database and create tables
db.connect()
db.create_tables([Ruling])

# Load the schema and use it to validate data
with open("assets/rulings_schema.json") as schema_file:
    schema = json.load(schema_file)


# Function to validate data against the schema
def validate_data(data, schema) -> None:
    # Implement validation logic here
    pass


# Function to process and insert data into the database
def process_and_insert_data(data) -> None:
    for item in data:
        # Validate the data against the schema
        if not validate_data(item, schema):
            logging.error(f"Invalid data: {item}")
            continue

        # Create a new Ruling object and save it to the database
        ruling = Ruling.create(
            card_name=item["card_name"],
            type=item["type"],
            text=item["text"],
            source_updated=datetime.datetime.strptime(
                item["source"]["updated"], "%d %B %Y")
            if item["source"]["updated"]
            else None,
            source_type=item["source"]["type"],
            source_version=item["source"]["version"],
        )
        ruling.save()


# Load the processed data
with open("assets/processed_data.json") as data_file:
    processed_data = json.load(data_file)

# Process and insert the data into the database
for _card_name, rulings in processed_data.items():
    for ruling in rulings:
        process_and_insert_data(ruling)

# Close the database connection
db.close()


# Additional functions for querying and manipulating the database can be added here


# Example function to query the database
def query_rulings_by_card_name(card_name):
    query = Ruling.select().where(Ruling.card_name == card_name)
    return [model_to_dict(ruling) for ruling in query]


# Example usage of the query function
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    example_card_name = "Example Card"
    example_rulings = query_rulings_by_card_name(example_card_name)
    for ruling in example_rulings:
        print(ruling)
