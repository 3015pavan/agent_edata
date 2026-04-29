"""
Comprehensive test harness for validating all 70 query types.
This script tests the query system against real-world examples.
"""

import sys
from typing import Dict, List, Optional

# 70 real-world queries organized by category
TEST_QUERIES = {
    "Student Self-Queries (5 queries)": [
        "What is my SGPA?",
        "Who am I in the ranking?",
        "How many subjects did I fail?",
        "Did I pass all subjects?",
        "What is my best subject?",
    ],
    "Name-based Lookups (5 queries)": [
        "Show me Abir's results",
        "Result of Pavan",
        "Tell me about Shweta",
        "Get me Veda's SGPA",
        "Find data for Rahul",
    ],
    "USN-based Lookups (5 queries)": [
        "Result of USN 1MS22CS001",
        "Get me 1MS22CS050",
        "Tell me about 1MS22IS010",
        "Show 1MS22EC999",
        "Find USN 1MS23CS100",
    ],
    "Subject Performance Queries (5 queries)": [
        "List students who failed in engineering chemistry lab",
        "Who passed in maths?",
        "Students with F in design thinking",
        "Did anyone fail in database management?",
        "Who got A+ in data structures?",
    ],
    "Subject-Level Failure Queries (5 queries)": [
        "List students who failed in chemistry",
        "Who got F in engineering mechanics?",
        "Students who flunked data structures",
        "Who messed up in systems programming?",
        "List students with GP 0 in algorithms",
    ],
    "Subject-Level Passing Queries (5 queries)": [
        "Students who didn't fail in physics",
        "Who passed in calculus?",
        "Students with high marks in signals",
        "Who scored highest in networks?",
        "Best performers in circuits",
    ],
    "SGPA Range Queries (2 queries)": [
        "Students with SGPA above 9",
        "Students with SGPA below 5",
    ],
    "Failure and Aggregation Queries (5 queries)": [
        "Who failed all subjects?",
        "How many students failed?",
        "Percentage of students who passed",
        "Most common failing grade",
        "Count students with any failure",
    ],
    "Top Performers and Rankings (5 queries)": [
        "Who is the topper?",
        "Top 5 students",
        "What is the average SGPA?",
        "Highest SGPA achieved",
        "Best student by class",
    ],
    "Any/All Conditions (5 queries)": [
        "Students with any F grade",
        "Students with all A+ grades",
        "Anyone who didn't fail",
        "All students with failing GP",
        "Who failed in any subject",
    ],
    "Search and Prefix (5 queries)": [
        "Students starting with 1MS22CS",
        "Names starting with A",
        "Find names with 'ar' in them",
        "USN prefix 1MS23",
        "Student names beginning with 'S'",
    ],
    "Rank and Performance Comparisons (5 queries)": [
        "Who has the lowest SGPA?",
        "Compare top and bottom students",
        "Average performance by subject",
        "Students above class average",
        "Underperformers in the class",
    ],
    "Grade-based Aggregations (5 queries)": [
        "How many got A+?",
        "Count of each grade",
        "What grades did everyone get?",
        "Most frequent grade",
        "Distribution of grades",
    ],
    "Complex and Multi-Intent Queries (7 queries)": [
        "Top student and total failures",
        "Who passed and average SGPA",
        "Failed count and topper name",
        "Best student and worst student",
        "Average SGPA and pass percentage",
        "Top 5 and bottom 5 students",
        "Total students and passing percentage",
    ],
    "Natural Language and Typos (5 queries)": [
        "list studnts who failed in chem lab",  # typo: studnts -> students
        "topr student in the class",  # typo: topr -> top
        "avrage sgpa of all",  # typo: avrage -> average
        "students who really messed up",
        "pavan's reslt please",  # typo: reslt -> result
    ],
    "Edge Cases (6 queries)": [
        "List all names",
        "Show every subject",
        "Empty query test",
        "What about GPAs?",
        "Who is best?",
        "Results?",
    ],
}

# Expected intent mappings for each query (for validation)
EXPECTED_INTENTS = {
    # Student Self-Queries
    "What is my SGPA?": ["GET_AVERAGE_SGPA", "CONTEXTUAL_ANSWER"],
    "Who am I in the ranking?": ["CONTEXTUAL_ANSWER"],
    "How many subjects did I fail?": ["GET_FAILED_COUNT", "CONTEXTUAL_ANSWER"],
    "Did I pass all subjects?": ["CONTEXTUAL_ANSWER"],
    "What is my best subject?": ["CONTEXTUAL_ANSWER"],
    
    # Name-based Lookups
    "Show me Abir's results": ["GET_RESULT_BY_NAME"],
    "Result of Pavan": ["GET_RESULT_BY_NAME"],
    "Tell me about Shweta": ["GET_RESULT_BY_NAME"],
    "Get me Veda's SGPA": ["GET_RESULT_BY_NAME", "CONTEXTUAL_ANSWER"],
    "Find data for Rahul": ["GET_RESULT_BY_NAME"],
    
    # USN-based Lookups
    "Result of USN 1MS22CS001": ["GET_RESULT_BY_USN"],
    "Get me 1MS22CS050": ["GET_RESULT_BY_USN"],
    "Tell me about 1MS22IS010": ["GET_RESULT_BY_USN"],
    "Show 1MS22EC999": ["GET_RESULT_BY_USN"],
    "Find USN 1MS23CS100": ["GET_RESULT_BY_USN"],
    
    # Subject Performance Queries
    "List students who failed in engineering chemistry lab": ["GET_FAILED_IN_SUBJECT"],
    "Who passed in maths?": ["GET_PASSED_IN_SUBJECT"],
    "Students with F in design thinking": ["GET_FAILED_IN_SUBJECT"],
    "Did anyone fail in database management?": ["GET_FAILED_IN_SUBJECT", "CONTEXTUAL_ANSWER"],
    "Who got A+ in data structures?": ["GET_STUDENTS_WITH_GRADE"],
    
    # Subject-Level Failure Queries
    "List students who failed in chemistry": ["GET_FAILED_IN_SUBJECT"],
    "Who got F in engineering mechanics?": ["GET_FAILED_IN_SUBJECT"],
    "Students who flunked data structures": ["GET_FAILED_IN_SUBJECT"],
    "Who messed up in systems programming?": ["GET_FAILED_IN_SUBJECT"],
    "List students with GP 0 in algorithms": ["GET_FAILED_IN_SUBJECT"],
    
    # Subject-Level Passing Queries
    "Students who didn't fail in physics": ["GET_PASSED_IN_SUBJECT"],
    "Who passed in calculus?": ["GET_PASSED_IN_SUBJECT"],
    "Students with high marks in signals": ["GET_PASSED_IN_SUBJECT"],
    "Who scored highest in networks?": ["GET_PASSED_IN_SUBJECT"],
    "Best performers in circuits": ["GET_PASSED_IN_SUBJECT"],
    
    # SGPA Range Queries
    "Students with SGPA above 9": ["GET_SGPA_RANGE"],
    "Students with SGPA below 5": ["GET_SGPA_RANGE"],
    
    # Failure and Aggregation Queries
    "Who failed all subjects?": ["GET_FAILED", "CONTEXTUAL_ANSWER"],
    "How many students failed?": ["GET_FAILED_COUNT"],
    "Percentage of students who passed": ["GET_PASS_PERCENTAGE"],
    "Most common failing grade": ["GET_MOST_FREQUENT_GRADE", "CONTEXTUAL_ANSWER"],
    "Count students with any failure": ["GET_FAILED_COUNT"],
    
    # Top Performers and Rankings
    "Who is the topper?": ["GET_TOPPER"],
    "Top 5 students": ["GET_TOP_N"],
    "What is the average SGPA?": ["GET_AVERAGE_SGPA"],
    "Highest SGPA achieved": ["GET_TOPPER", "CONTEXTUAL_ANSWER"],
    "Best student by class": ["GET_TOPPER"],
    
    # Any/All Conditions
    "Students with any F grade": ["GET_FAILED"],
    "Students with all A+ grades": ["CONTEXTUAL_ANSWER"],
    "Anyone who didn't fail": ["GET_ALL_PASSING"],
    "All students with failing GP": ["GET_GP_ZERO_ANY"],
    "Who failed in any subject": ["GET_FAILED"],
    
    # Search and Prefix
    "Students starting with 1MS22CS": ["GET_USN_PREFIX"],
    "Names starting with A": ["GET_NAME_PREFIX"],
    "Find names with 'ar' in them": ["GET_NAME_PREFIX", "CONTEXTUAL_ANSWER"],
    "USN prefix 1MS23": ["GET_USN_PREFIX"],
    "Student names beginning with 'S'": ["GET_NAME_PREFIX"],
    
    # Rank and Performance Comparisons
    "Who has the lowest SGPA?": ["CONTEXTUAL_ANSWER"],
    "Compare top and bottom students": ["CONTEXTUAL_ANSWER", "MULTI_INTENT_QUERY"],
    "Average performance by subject": ["CONTEXTUAL_ANSWER"],
    "Students above class average": ["CONTEXTUAL_ANSWER"],
    "Underperformers in the class": ["CONTEXTUAL_ANSWER"],
    
    # Grade-based Aggregations
    "How many got A+?": ["CONTEXTUAL_ANSWER"],
    "Count of each grade": ["CONTEXTUAL_ANSWER"],
    "What grades did everyone get?": ["CONTEXTUAL_ANSWER"],
    "Most frequent grade": ["GET_MOST_FREQUENT_GRADE"],
    "Distribution of grades": ["CONTEXTUAL_ANSWER"],
    
    # Complex and Multi-Intent Queries
    "Top student and total failures": ["MULTI_INTENT_QUERY"],
    "Who passed and average SGPA": ["MULTI_INTENT_QUERY"],
    "Failed count and topper name": ["MULTI_INTENT_QUERY"],
    "Best student and worst student": ["MULTI_INTENT_QUERY"],
    "Average SGPA and pass percentage": ["MULTI_INTENT_QUERY"],
    "Top 5 and bottom 5 students": ["MULTI_INTENT_QUERY"],
    "Total students and passing percentage": ["MULTI_INTENT_QUERY"],
    
    # Natural Language and Typos
    "list studnts who failed in chem lab": ["GET_FAILED_IN_SUBJECT"],  # Fuzzy matching
    "topr student in the class": ["GET_TOPPER"],  # Fuzzy matching
    "avrage sgpa of all": ["GET_AVERAGE_SGPA"],  # Fuzzy matching
    "students who really messed up": ["GET_FAILED"],  # Natural language
    "pavan's reslt please": ["GET_RESULT_BY_NAME"],  # Typo and contextual
    
    # Edge Cases
    "List all names": ["CONTEXTUAL_ANSWER"],
    "Show every subject": ["GET_ALL_SUBJECTS"],
    "Empty query test": [],
    "What about GPAs?": ["CONTEXTUAL_ANSWER"],
    "Who is best?": ["GET_TOPPER", "CONTEXTUAL_ANSWER"],
    "Results?": ["CONTEXTUAL_ANSWER"],
}

def count_coverage() -> Dict[str, int]:
    """Count coverage of expected intents."""
    total = len(TEST_QUERIES) - 1  # Exclude "Edge Cases"
    covered_queries = 0
    total_queries = 0
    
    for category, queries in TEST_QUERIES.items():
        if category == "Edge Cases":
            continue
        total_queries += len(queries)
        for query in queries:
            if query in EXPECTED_INTENTS and EXPECTED_INTENTS[query]:
                covered_queries += 1
    
    return {
        "total": total_queries,
        "covered": covered_queries,
        "percentage": round((covered_queries / total_queries * 100), 1) if total_queries > 0 else 0,
    }

def print_coverage_report() -> None:
    """Print a detailed coverage report."""
    print("\n" + "="*80)
    print("COMPREHENSIVE QUERY TEST SUITE - COVERAGE REPORT")
    print("="*80 + "\n")
    
    coverage = count_coverage()
    print(f"Total Queries: {coverage['total']}")
    print(f"Covered Queries: {coverage['covered']}")
    print(f"Coverage: {coverage['percentage']}%")
    
    print("\n" + "-"*80)
    print("QUERY BREAKDOWN BY CATEGORY")
    print("-"*80 + "\n")
    
    for category, queries in TEST_QUERIES.items():
        print(f"\n{category}:")
        for idx, query in enumerate(queries, 1):
            if query in EXPECTED_INTENTS:
                intents = EXPECTED_INTENTS[query]
                if intents:
                    intent_str = " | ".join(intents)
                    print(f"  {idx}. {query}")
                    print(f"     Intent: {intent_str}")
                else:
                    print(f"  {idx}. {query}")
                    print(f"     Intent: UNKNOWN/EDGE CASE")
            else:
                print(f"  {idx}. {query}")
                print(f"     Intent: NOT MAPPED")

def print_gap_analysis() -> None:
    """Print gaps analysis."""
    print("\n" + "="*80)
    print("GAP ANALYSIS")
    print("="*80 + "\n")
    
    gaps = {
        "Gap 1: SGPA Range (HIGH)": ["Students with SGPA above 9", "Students with SGPA below 5"],
        "Gap 2: Pass Percentage (HIGH)": ["Percentage of students who passed"],
        "Gap 3: Multi-Intent Parser (HIGH)": [
            "Top student and total failures",
            "Who passed and average SGPA",
            "Failed count and topper name",
            "Best student and worst student",
            "Average SGPA and pass percentage",
            "Top 5 and bottom 5 students",
            "Total students and passing percentage",
        ],
        "Gap 4: Natural Language (MEDIUM)": [
            "students who really messed up",
        ],
        "Gap 5: Fuzzy Matching (MEDIUM)": [
            "list studnts who failed in chem lab",
            "topr student in the class",
            "avrage sgpa of all",
            "pavan's reslt please",
        ],
    }
    
    for gap, queries in gaps.items():
        print(f"{gap}:")
        for query in queries:
            print(f"  - {query}")
        print()

if __name__ == "__main__":
    print_coverage_report()
    print_gap_analysis()
    
    print("\n" + "="*80)
    print("TEST EXECUTION INSTRUCTIONS")
    print("="*80 + "\n")
    print("To run actual query validation:")
    print("1. Start the backend: python -m uvicorn backend.main:app --reload")
    print("2. Create a client script to send HTTP requests to http://localhost:8000/query")
    print("3. Iterate through all 70 queries and check response intents")
    print("4. Compare actual intents with EXPECTED_INTENTS mapping")
    print("5. Log any mismatches or failures\n")
