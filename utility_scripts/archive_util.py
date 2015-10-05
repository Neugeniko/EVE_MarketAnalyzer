import sys, gzip, StringIO, sys, math, getopt, time, json, socket
#from os import path, environ, getcwd
import pypyodbc
import ConfigParser
from datetime import datetime, timedelta
from os import environ, path, getcwd, chdir
thread_exit_flag = False

### PATH STUFF ###
local_path = path.dirname( path.realpath(__file__) )
archive_config_path = path.join( local_path, "archive_config.json" )
config_info = json.load( open(archive_config_path) )

base_path = path.split( path.dirname( path.realpath(__file__) ) )[0]

sql_file_path = path.join( base_path,'SQL' )
DEV_localpath = path.join( base_path,'init.ini' )
ALT_localpath = path.join( base_path,'init_local.ini' )
conf = ConfigParser.ConfigParser()
conf.read( [DEV_localpath, ALT_localpath] )

#### PROGRAM GLOBALS ####
run_arg = conf.get( 'ARCHIVE', 'default_run_arg' )
gDebug = False

def test_connection( odbc_dsn, table_name, table_create_file="", debug=gDebug ):
	db_con = pypyodbc.connect( 'DSN=%s' % odbc_dsn )
	db_cur = db_con.cursor()
	
	return_bool = True
	if table_create_file:
		if debug: print "creating table %s.%s ***WARNING: DESTRUCTIVE***" % (odbc_dsn, table_name)
		try:
			create_table ( db_con, db_cur, table_create_file, debug )
		except Exception as e:
			print "***Unable to create_table() %s.%s: %s" % (odbc_dsn, table_name, e)
			return_bool = False

	test_query = '''SELECT count(*) FROM {table_name} LIMIT 10'''
	test_query = test_query.format( table_name = table_name )	
	try:
		if debug: print "\t%s" % test_query
		db_cur.execute(test_query)
	except Exception as e:
		print "***test_connection() %s.%s failed: %s" % (odbc_dsn, table_name, e)
		return_bool = False
	
	db_con.close()	#all connections are function-only
	return return_bool

def create_table ( db_con, db_cur, table_create_file, debug=gDebug ):
	global sql_file_path
	table_filepath = path.join( sql_file_path, table_create_file ) 
	if debug: print table_filepath 
	table_create_query = open( table_filepath ).read()
	table_create_commands = table_create_query.split(';')
	try:
		for command in table_create_commands:
			if debug: print "\t%s" % command
			db_cur.execute( command )
			db_con.commit()
	except Exception as e:
		if e[0] == "HY090":
			print "***Suppressed HY090 ERR: Invalid string or buffer length"
			### environment issue.  creates table, but SQLite ODBC connector has a driver issue ###
			### If table is not created, test read will fail ###
		else:
			raise
	
def pull_data ( odbc_dsn, table_name, query_file="ALL", debug=gDebug ):
	queryStr = ""
	if query_file == "ALL":
		queryStr = '''SELECT * FROM {table_name}'''
		queryStr = queryStr.format( table_name=table_name )
	else:
		query_path = path.join( sql_file_path, query_file )
		queryStr = open( query_path ).read()
	if debug: print queryStr
	
	db_con = pypyodbc.connect( 'DSN=%s' % odbc_dsn )
	db_cur = db_con.cursor()
	
	db_cur.execute(queryStr)
	dataObj = db_cur.fetchall()
	
	db_con.close()	#all connections are function-only
	return dataObj

def prepare_write_data ( dataObj, table_name, debug=gDebug ):	#TODO: easier way to pipe data from one to the other?
	table_headers = config_info['tables'][table_name]['cols']
	column_types  = config_info['tables'][table_name]['types']	#TODO: this is probably bad
	
	write_str = '''INSERT INTO {table_name} ({table_headers}) VALUES'''
	write_str = write_str.format(
					table_name    = table_name,
					table_headers = ','.join(table_headers)
					)
	
	if debug: print write_str 
	value_str = ""
	print_single = 0
	for row in dataObj:
		col_index = 0	#for tracking headers
		data_values = []
		for col in row:
			header   = table_headers[col_index]
			dataType = column_types[header].lower()
			data_str = ''
			
			if dataType == 'number':
				data_str = str(col)
			elif dataType == 'string':
				data_str = "'%s'" % col
			else:
				print "***unsupported dataType: header=%s dataType=%s" % (header, dataType)
			
			data_values.append(data_str)
			col_index += 1
		tmp_value_str = ','.join(data_values)
		tmp_value_str = tmp_value_str.rstrip(',')
		#if debug: print tmp_value_str
		value_str = "%s (%s)," % (value_str, tmp_value_str)
		
		if print_single < 1 and debug:
			print value_str
			print_single += 1
	value_str = value_str.rstrip(',')
	
	duplicate_str = ""
	#duplicate_str = '''ON DUPLICATE KEY UPDATE '''
	#for header in table_headers:
	#	duplicate_str = "%s %s=%s," % (duplicate_str, header, header)
	#	
	#duplicate_str = duplicate_str.rstrip(',')
	#if debug: print duplicate_str
	commit_str = '''{write_str} {value_str} {duplicate_str}'''
	commit_str = commit_str.format(
					write_str     = write_str,
					value_str     = value_str, 
					duplicate_str = duplicate_str
					)
				
	return commit_str 
	
def write_SQL ( commit_str, odbc_dsn, table_name, debug=gDebug ):
	db_con = pypyodbc.connect( 'DSN=%s' % odbc_dsn )
	db_cur = db_con.cursor()
	
	db_cur.execute(commit_str).commit()
	
	db_con.close()

def main():
	global run_arg
	global gDebug
	### Load MAIN args ###
	try:
		opts, args = getopt.getopt( sys.argv[1:], 'h:l', ['config=', 'debug'] )
	except getopt.GetoptError as e:
		print str(e)
		print 'unsupported argument'
		sys.exit()
	for opt, arg in opts:
		if opt == '--config':
			run_arg = arg
		elif opt == '--debug':
			gDebug=True
		else:
			assert False

	debug = gDebug
	
	try:
		config_info['args'][run_arg]
	except KeyError as e:
		print "Invalid config '%s'" % run_arg
		sys.exit(2)
	print "running profile: %s" % run_arg	
	if debug: print "archive_config_path = %s" % archive_config_path
	if debug: print "sql_file_path = %s" % sql_file_path	
	if debug: print config_info['args'][run_arg]
	
	### Config information ###
	export_import          =      config_info['args'][run_arg]['export_import'].lower()
	destination_DSN        =      config_info['args'][run_arg]['destination_DSN']
	destructive_write      = int( config_info['args'][run_arg]['destructive_write'] )
	clean_up_archived_data = int( config_info['args'][run_arg]['clean_up_archived_data'] )
	
	### Run through archive operations ###
	for table_name,info_dict in config_info['args'][run_arg]['tables_to_run'].iteritems():
		ODBC_DSN   = info_dict['ODBC_DSN']
		create     = info_dict['create']
		
		print "Testing connections"
		### Sort read/write ODBC handles ###
		read_DSN  = ""
		write_DSN = ""
		if export_import == 'export':
			read_DSN  = ODBC_DSN
			write_DSN = destination_DSN
		elif export_import == 'import':
			read_DSN  = destination_DSN
			write_DSN = ODBC_DSN
		else:
			print "***Unsupported export_import value: %s" % export_import
			sys.exit(2)
		if debug: print "\tREAD = %s.%s" % (read_DSN, table_name)
		if debug: print "\tWRITE = %s.%s" % (write_DSN, table_name)
		
		#sys.exit()
		### test/configure WRITE location ###
		write_table_ok = False
		if destructive_write == 1: #TODO: better method to control table DROP
			write_table_ok = test_connection( write_DSN, table_name, create, debug )
		else:
			write_table_ok = test_connection( write_DSN, table_name, "", debug )
		
		if write_table_ok:
			print "Validated table connection"
			print "\tWRITE=%s.%s" % (write_DSN, table_name)
		else:
			print "***Unable to connect to table: %s.%s" % (write_DSN, table_name)
			sys.exit(2)
			
		### test/configure READ location ###
		#read_table_ok = False
		read_table_ok = True
		#read_table_ok = test_connection( read_DSN, table_name, "", debug )
		
		if read_table_ok:
			print "Validated table connection"
			print "\tREAD=%s.%s" % (read_DSN, table_name)
		else:
			print "***Unable to connect to table: %s.%s" % (read_DSN, table_name)
			sys.exit(2)
			
		print "Pulling data for archive"
		### Fetch data for import/export ###
		table_data = pull_data( read_DSN, table_name, query_file, debug )
		
		print "Preparing data to archive"
		write_string = ""
		write_string = prepare_write_data ( table_data, table_name, debug )
		
		print "Writing data to archive"
		write_SQL ( write_string, write_DSN, table_name, debug )
if __name__ == "__main__":
	try:
		main()
	except KeyboardInterrupt:
		thread_exit_flag = True
		raise