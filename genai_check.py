from time import sleep
from typing import Tuple
import os
import google.generativeai as genai
from dotenv import load_dotenv
import textwrap
import json
import argparse
from akg import AKGException, akg_logging_config
import logging
from tracking import load_tracking, save_tracking
import sys 

# Load environment variables from .env file
load_dotenv()

# a suitable format for the line in the .env file is:
# GOOGLE_API_KEY="Your-API-Key-Here"
# include .env in .gitignore.

# Obtain the API key from Google AI studio, currently at:
# https://aistudio.google.com/apikey

# Get the API key from the environment
GOOGLE_API_KEY = os.getenv('GOOGLE_API_KEY')

if not GOOGLE_API_KEY:
    raise ValueError("API key not found. Please set it in your .env file.")

genai.configure(api_key=GOOGLE_API_KEY)

def genai_check(filename:str)->Tuple[bool,str]:
    """Check (using generative AI model) if the file is of the type we require
    for our study. See prompt_template below for the exact details.

    Args:
        filename (str): The name of the file to check.
    Returns:
        bool: True if the file is of the required type, False otherwise.
        str: Explanation of the result.
    """
    # This is an arbitrary chunk at the start of the file being checked, to 
    # avoid unnecessarily reading too much. We're only checking the format.
    max_chars = 500
    # Read the content of the file
    try:
        with open(filename, 'r') as f:
            file_content = f.read(max_chars)
    except FileNotFoundError:
        print(f"Error: The file '{filename}' was not found.")
        exit()

    # --- Interaction with Gemini ---
    # Select the Gemini model. 
    # Gemini itself advises me that to minimize non-deterministic behavior, set temperature to 0.0
    # (with some provisos - there is some inherent randomness in the model and the remote compute platform, and even 
    # a specific labelled model may be subject to minor updates)
    generation_config = genai.GenerationConfig(
        temperature=0.0
    )

    # Pass the config when creating the model instance
    # The model we're using here is that given by Gemini's template code (gemini-1.5-flash)
    # "Our fastest multimodal model with great performance for diverse, repetitive tasks and a 1 million token context window."
    # However things are moving fast and it's flagged as a legacy model scheduled for retirement on 25/9/2025
    # TODO: retry using gemini-2.0-flash as prompted in 
    # https://cloud.google.com/vertex-ai/generative-ai/docs/learn/model-versions
    #
    model = genai.GenerativeModel(
        'gemini-1.5-flash',
        generation_config=generation_config
    )
    # Create the prompt, providing both the instructions and the file content
    prompt_template = """
    Analyze the following CSV content. Respond in a valid JSON format with two keys:
    1. "answer": a boolean value (true or false).
    2. "reason": a string explaining your reasoning.

    Does this file contain autism or ASD gene expression data with each row holding (among other things) a gene name, a pvalue, and a log fold change? 
    These don't have to be the only columns present, but they must be included. They can come in any order, and the file can have a header row.

    --- CSV CONTENT START ---
    {csv_data}
    --- CSV CONTENT END ---
    """
    prompt = textwrap.dedent(prompt_template)

    # Send the prompt to the model
    response = model.generate_content(prompt.format(csv_data=file_content))
    # Get the raw text from the response
    raw_text = response.text
    
    # Clean the text to extract only the JSON part
    # This handles cases where the model wraps the JSON in ```json ... ```
    start = raw_text.find('{')
    end = raw_text.rfind('}')
    
    if start != -1 and end != -1:
        json_string = raw_text[start:end+1]
    else:
        json_string = raw_text # just pass through to the same error handling below

    try:
        parsed_response = json.loads(json_string)

        # Now you can access the structured data
        is_suitable = parsed_response['answer']      # This will be True or False
        explanation = parsed_response['reason']      # This is the explanation string

        return is_suitable, explanation

    except (json.JSONDecodeError, KeyError) as e:
        print(f"Error parsing the model's response: {e}")
        print(f"Raw response: {response.text}")

    return False, "File format not supported"

if __name__ == "__main__":

    command_line_str = ' '.join(sys.argv)

    # manage the command line options
    parser = argparse.ArgumentParser(description='Check the format of chosen files using Google Gemini AI model.')
    parser.add_argument('-i', '--input_dir', default='data', help='Destination top-level directory for input data files (output files also written here)')
    parser.add_argument('-t', '--tracking_file', default='akg_tracking.xlsx', help='Tracking file name. This file is created in the top-level directory.')
    parser.add_argument('-l', '--log', default='genai_check.log', help='Log file name. This file is created in the top-level directory.')
    parser.add_argument('-e', '--exclude', action='store_true', help='Set the tracking file exclude value to True for the files that are not suitable')
    parser.add_argument('-c', '--check-one-file', default=None, help='Check this one file only, in the input directory')

    # argparse populates an object using parse_args
    # extract its members into a dict and from there into variables if used in more than one place
    config = vars(parser.parse_args())

    main_dir = config['input_dir']
    one_file = config['check_one_file']
    record_exclusions = config['exclude']

    if one_file:
        filename = one_file

        is_valid, explanation = genai_check(filename)
        if is_valid:
            print(f"File '{filename}' is of the required type.")
        else:
            print(f"File '{filename}' is not of the required type.")
        print(f"Explanation: {explanation}")
    else:
        if not os.path.isdir(main_dir):
            raise AKGException(f"data_convert: data directory {main_dir} must exist") 

        akg_logging_config(os.path.join(main_dir, config['log']))
        logging.info(f"Program executed with command: {command_line_str}")

        logging.info(f'Top-level data directory {os.path.realpath(main_dir)}')

        # create the tracking file    
        tracking_file = config['tracking_file']
        tracking_file = os.path.join(main_dir, tracking_file)
        if not os.path.exists(tracking_file):
            raise AKGException(f'No tracking file {tracking_file}, cannot track results or determine which files to process')

        # loop over all the files identified by the tracking file and process them
        df = load_tracking(tracking_file)

    # TODO: remove loop iteration, do sthg more pythonic
        for index, row in df.iterrows():
            root = row['path']
            file = row['file']
            # only operate on those files created by data_convert
            # ignore excluded flag at present, to make a comparison
            if row['step'] == 1:
                if row['excl']:
                    logging.info(f"File: {file_path} flagged as excluded")
                file_path = os.path.join(root, file)
                logging.info(f"Processing file: {file_path}")
                is_valid, explanation = genai_check(file_path)
                if is_valid:
                    logging.info(f"File '{file_path}' is of the required type.")
                else:
                    logging.info(f"File '{file_path}' is not of the required type.")
                logging.info(f"Explanation: {explanation}")
                df.loc[int(index),'suitable'] = is_valid
                df.loc[int(index),'suitablereason'] = explanation
                if not is_valid and record_exclusions:
                    df.loc[int(index),'excl'] = True
                    logging.info(f"Excluding file: {file_path}")
                # insert a delay of 10s to avoid hammering the API and hitting rate limits
                sleep(10)

        save_tracking(df, tracking_file)
