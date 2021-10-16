from py2neo import Graph
from datetime import datetime
import sys
import argparse
import pandas as pd

def banner():
    print("""   ______                ____  __                      __""")
    print("""  / ____/___  ____  ____/ / / / /___  __  ______  ____/ /""")
    print(""" / / __/ __ \/ __ \/ __  / /_/ / __ \/ / / / __ \/ __  / """)
    print("""/ /_/ / /_/ / /_/ / /_/ / __  / /_/ / /_/ / / / / /_/ /  """)
    print(  "\____/\____/\____/\__,_/_/ /_/\____/\__,_/_/ /_/\__,_/   """)

def arguments():
    argparser = argparse.ArgumentParser(description="BloodHound Wrapper to determine the Busiest Attack Paths to High Value targets.", add_help=True, epilog="Attackers think in graphs, Defenders think in actions, Management think in charts.")
    parsegroupdb = argparser.add_argument_group('Neo4jConnection')
    parsegroupdb.add_argument("-u", "--username", default="neo4j", help="Neo4j Database Username (Default: neo4j)", type=str)
    parsegroupdb.add_argument("-p", "--password", default="neo4j", help="Neo4j Database Password (Default: neo4j)", type=str)
    parsegroupdb.add_argument("-s", "--server", default="bolt://localhost:7687", help="Neo4j server Default: bolt://localhost:7687)", type=str)
    parsegroupoutput = argparser.add_argument_group('Output Formats')
    parsegroupoutput.add_argument("-o", "--output-format", default="stdout", help="Output formats supported: stdout, csv, md (markdown).", type=str, choices=["stdout", "csv", "md", "markdown"])
    parsegroupoutput.add_argument("-f", "--output-filename", default="goodhound.csv", help="File path and name to save the csv output.", type=str)
    parsegroupqueryparams = argparser.add_argument_group('Query Parameters')
    parsegroupqueryparams.add_argument("-r", "--results", default="5", help=("The number of busiest paths to process. The higher the number the longer the query will take. Default: 5"), type=int)
    parsegroupschema = argparser.add_argument_group('Schema')
    parsegroupschema.add_argument("-sch", "--schema", help="Optionally select in a text file containing custom cypher queries to add labels to the neo4j database. e.g. Use this if you want to add the highvalue label to assets.", type=str)
    args = argparser.parse_args()
    return args

def db_connect(args):
    try:
        graph = Graph(args.server, user=args.username, password=args.password)
        return graph    
    except:
        print("Database connection failure.")
        sys.exit(1)

def schema(graph, args):
    try:
        with open(args.schema,'r') as schema_query:
            lines = schema_query.read()
            query = """%s""" %lines
            graph.run(lines)
    except:
        print("Error setting custom schema.")
        sys.exit(1)

def shortestpath(graph, starttime):
    """Runs a shortest path query for all AD groups to high value targets. Returns a list of groups."""
    query_shortestpath="""match p=shortestpath((g:Group {highvalue:FALSE})-[*1..]->(n {highvalue:TRUE})) return distinct(g.name) as groupname, min(length(p)) as hops"""
    query_test="""match p=shortestpath((g:Group {highvalue:FALSE})-[*1..]->(n {highvalue:TRUE})) WHERE tolower(g.name) =~ 'admin.*' return distinct(g.name) as groupname, min(length(p)) as hops""" 
    print("Running query")
    groupswithpath=graph.run(query_shortestpath)
    querytime = round((datetime.now()-starttime).total_seconds() / 60)
    print("Finished query in : {} Minutes".format(querytime))
    return groupswithpath

def busiestpath(groupswithpath, graph, args):
    """Calculate the busiest paths by getting the number of users in the Groups that have a path to Highvalue, sorting the result, calculating some statistics and returns a list."""
    totalenablednonadminsquery="""match (u:User {highvalue:FALSE, enabled:TRUE}) return count(u)"""
    totalenablednonadminusers = int(graph.run(totalenablednonadminsquery).evaluate())
    usercount=[]
    users=[]
    grouploopstart = datetime.now()
    print("Counting Users in Groups")
    for g in groupswithpath:
        group = g.get('groupname')
        hops = g.get('hops')
        print (f"Processing group: {group}................................................", end='\r')
        query_num_members = """match (u:User {highvalue:FALSE, enabled:TRUE})-[:MemberOf*1..]->(g:Group {name:"%s"}) return count(distinct(u))""" % group
        query_group_members = """match (u:User {highvalue:FALSE, enabled:TRUE})-[:MemberOf*1..]->(g:Group {name:"%s"}) return u.name""" % group
        num_members = int(graph.run(query_num_members).evaluate())
        group_members = graph.run(query_group_members)
        for m in group_members:
            member = m.get('u.name')
            users.append(member)
        percentage=round(float((num_members/totalenablednonadminusers)*100), 1)
        result = [group, num_members, percentage, hops]
        usercount.append(result)
    top_paths = (sorted(usercount, key=lambda i: -i[1])[0:args.results])
    total_unique_users = len((pd.Series(users)).unique())
    total_users_percentage = round(((total_unique_users/totalenablednonadminusers)*100),1)
    grandtotals = [{"Total Non-Admins with a Path":total_unique_users, "Percentage of Total Enabled Non-Admins":total_users_percentage}]
    #grouploopfinishtime = datetime.now()
    #grouplooptime = round((grouploopfinishtime-grouploopstart).total_seconds() / 60)
    #print("\nFinished counting users in: {} minutes.".format(grouplooptime))
    return top_paths, grandtotals

def query(top_paths, starttime):
    """Generate a replayable query for each finding for Bloodhound visualisation."""
    results = []
    for t in top_paths:
        group = t[0]
        num_users = int(t[1])
        percentage = float(t[2])
        hops = int(t[3])
        previous_hop = hops - 1
        query = """match p=((g:Group {name:"%s"})-[*%s..%s]->(n {highvalue:true})) return p""" %(group, previous_hop, hops)
        result = [group, num_users, percentage, hops, query]
        results.append(result)
    finish = datetime.now()
    totalruntime = round((finish - starttime).total_seconds() / 60)
    print("\nTotal runtime: {} minutes.".format(totalruntime), end='\n\n')
    return results

def output(results, grandtotals, args):
    pd.set_option('display.max_colwidth', None)
    totaldf = pd.DataFrame(grandtotals)
    resultsdf = pd.DataFrame(results, columns=["Starting Group", "Number of Enabled Non-Admins with Path", "Percent of Total Enabled Non-Admins", "Number of Hops", "Bloodhound Query"])
    if args.output_format == "stdout":
        print("GRAND TOTALS")
        print("============")
        print(totaldf.to_string(index=False))
        print("BUSIEST PATHS")
        print("-------------\n")
        print (resultsdf.to_string(index=False))
    elif args.output_format == ("md" or "markdown"):
        print (totaldf.to_markdown(index=False))
        print (resultsdf.to_markdown(index=False))
    else:
        mergeddf = totaldf.append(resultsdf, ignore_index=True, sort=False)
        mergeddf.to_csv(args.output_filename, index=False)


def main():
    args = arguments()
    banner()
    graph = db_connect(args)
    starttime = datetime.now()
    if args.schema:
        schema(graph, args)
    groupswithpath = shortestpath(graph, starttime)
    top_paths, grandtotals = busiestpath(groupswithpath, graph, args)
    results = query(top_paths, starttime)
    output(results, grandtotals, args)

if __name__ == "__main__":
    main()