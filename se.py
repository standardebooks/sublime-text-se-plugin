from io import BytesIO
import os
import re
import urllib.parse
import urllib.request
import webbrowser

from lxml import etree

import sublime
import sublime_plugin

def get_sgml_regions(view):
	"""Find all XML and HTML scopes in the specified view."""
	return view.find_by_selector("text.xml, text.html.basic - embedding.php")

def get_sgml_regions_containing_cursors(view):
	"""Find the SGML region(s) that the cursor(s) are in for the specified view."""
	cursors = [cursor for cursor in view.sel()] # can't use `view.sel()[:]` because it gives an error `TypeError: an integer is required`
	regions = get_sgml_regions(view)
	for region_index, region in enumerate(regions):
		cursors_to_remove = []
		for cursor in cursors:
			if region.contains(cursor):
				yield (region, region_index, cursor)
				cursors_to_remove.append(cursor)
			elif region.begin() > cursor.end(): # cursor before this region
				cursors_to_remove.append(cursor)
			elif cursor.begin() > region.end(): # found all cursors in this region
				break
		if region_index < len(regions) - 1: # no point removing cursors from those left to find if no regions left to search through
			for cursor in cursors_to_remove:
				cursors.remove(cursor)
			if len(cursors) == 0:
				break

def is_cursor_inside_sgml(view):
	"""Return True if at least one cursor is within XML or HTML syntax."""
	return next(get_sgml_regions_containing_cursors(view), None) is not None

def get_selection(view):
	"""Get the currently selected text, or None"""

	for region in view.sel():
		return view.substr(region)

	return None

def get_group_view(window, group, index):
	"""Get the view at the given index in the given group."""
	# Cribbed from the TabsExtra package, MIT license

	sheets = window.sheets_in_group(int(group))
	sheet = sheets[index] if -1 < index < len(sheets) else None
	view = sheet.view() if sheet is not None else None

	return view

def is_se_file(view):
	"""True if the file has a filename, and we can find the container.xml file for it in its local tree"""

	if view.file_name() and get_container_path(view.file_name()):
		return True

	return False

def get_container_path(filename):
	file_dir = os.path.dirname(os.path.abspath(filename))

	# Check three dirs up for the ./src/ folder
	src_dir = os.path.abspath(os.path.join(file_dir, os.pardir, os.pardir, os.pardir, "src"))

	# Check two dirs up
	if not os.path.isdir(src_dir):
		src_dir = os.path.abspath(os.path.join(file_dir, os.pardir, os.pardir, "src"))

		# Check one dir up
		if not os.path.isdir(src_dir):
			src_dir = os.path.abspath(os.path.join(file_dir, os.pardir, "src"))

			# Check current dir
			if not os.path.isdir(src_dir):
				src_dir = os.path.abspath(os.path.join(file_dir, "src"))

	meta_inf_path = os.path.abspath(os.path.join(src_dir, "META-INF", "container.xml"))

	if not os.path.isfile(meta_inf_path):
		return None

	return meta_inf_path

def get_metadata_file_path(filename):
	"""
	Get the metadata file path for a given XHTML filename.
	Check for META-INF in the current dir, then up to two dirs up, and one dir down.
	"""

	# We have ./src/, now get the container file path
	meta_inf_path = get_container_path(filename)

	with open(meta_inf_path, "r", encoding="utf8") as file:
		meta_inf_dom = etree.fromstring(str.encode(file.read().replace(" xmlns=\"urn:oasis:names:tc:opendocument:xmlns:container\"", "")))

	metadata_file_path = meta_inf_dom.xpath("/container/rootfiles/rootfile/@full-path", namespaces={"container": "urn:oasis:names:tc:opendocument:xmlns:container"})[0]

	return  os.path.abspath(os.path.join(os.path.dirname(meta_inf_path), os.pardir, metadata_file_path))

class SeOpenMetadataFileCommand(sublime_plugin.WindowCommand):
	"""Contains the se_open_metadata_file command"""

	def run(self, group=-1, index=-1):
		"""Entry point for the se_open_metadata_file command."""

		filename = ""
		if group < 0 and index < 0:
			# We get here if we right-clicked on the window contents
			filename = self.window.active_view().file_name()
		else:
			# We get here if we right-clicked on a tab
			filename = get_group_view(self.window, group, index).file_name()

		try:
			metadata_file_path = get_metadata_file_path(os.path.abspath(filename))
			self.window.open_file(metadata_file_path)
		except:
			self.window.status_message("Couldn’t locate SE ebook metadata file.")

	def is_visible(self, group=-1, index=-1):
		"""
		Is this command visible in the right-click menu?
		True if the view contains SGML
		group and index are magic variables passed by ST, via the Tab Context.sublime-menu file
		"""

		if group < 0 and index < 0:
			# We get here if we right-clicked on the window contents
			return is_se_file(self.window.active_view())

		# We get here if we right-clicked on a tab
		return is_se_file(get_group_view(self.window, group, index))

class SeSearchSourceCommand(sublime_plugin.TextCommand):
	"""Contains the se_search_source command"""
	hathi_source_cache = {}

	def run(self, edit):
		"""Entry point for the se_search_source command. The `edit` param is required by ST"""
		# We can't use pathlib because we're stuck on Python 3.3 with ST

		if not self.view.file_name():
			return

		selection = get_selection(self.view)

		if not selection:
			return

		selection = selection.strip()

		try:
			metadata_file_path = get_metadata_file_path(os.path.abspath(self.view.file_name()))
		except:
			self.view.window().status_message("Couldn’t locate SE ebook metadata file.")

		try:
			with open(metadata_file_path, "r", encoding="utf8") as file:
				metadata_dom = etree.fromstring(str.encode(file.read().replace(" xmlns=\"http://www.idpf.org/2007/opf\"", "")))

			sources = metadata_dom.xpath("/package/metadata/dc:source/text()", namespaces={"dc": "http://purl.org/dc/elements/1.1/", "opf": "http://www.idpf.org/2007/opf"})
		except:
			self.view.window().status_message("Couldn’t read SE ebook metadata file located in {}".format(metadata_file_path))
			return

		for source in sources:
			if source.startswith("https://books.google."):
				webbrowser.open_new_tab(source + "&q=" + urllib.parse.quote("\"" + selection + "\""))
				return

			if source.startswith("https://www.google.com/books"):
				webbrowser.open_new_tab(source + "?gbpv=1&bsq=" + urllib.parse.quote("\"" + selection + "\""))

			if source.startswith("https://archive.org"):
				# IA chokes on non-letter characters in search strings
				webbrowser.open_new_tab(source.strip("/") + "/search/" + urllib.parse.quote("\"" + re.sub(r"[^A-Za-z0-9\s]", "", selection) + "\""))
				return

			if source.startswith("https://catalog.hathitrust.org"):
				# The HathiTrust catalog record URL doesn't give us a hint as to the scan URL.
				# So we have to fetch the page, parse it, and cache the results.

				if source not in self.hathi_source_cache:
					try:
						page = urllib.request.urlopen(source)

						parser = etree.HTMLParser()
						tree = etree.parse(BytesIO(page.read()), parser)
						hathi_sources = tree.xpath("//a[contains(normalize-space(.), 'Full view')]/@href")

						if hathi_sources:
							if "hdl.handle.net" in hathi_sources[0]:
								self.hathi_source_cache[source] = re.sub(r"^https?://hdl\.handle\.net/[0-9]+/", r"", hathi_sources[0])
							else:
								self.hathi_source_cache[source] = re.sub(r"^.+?/([^/]+$)", r"\1", hathi_sources[0])

					except:
						self.view.window().status_message("Couldn’t read source: {}".format(source))
						return

				if source in self.hathi_source_cache:
					webbrowser.open_new_tab("https://babel.hathitrust.org/cgi/pt/search?q1=" + urllib.parse.quote("\"" + selection + "\"") + ";id=" + self.hathi_source_cache[source])

				return

		self.view.window().status_message("Couldn’t recognize source URL.")

	def is_enabled(self):
		"""
		Is this command visible in the context menu?
		True if the view contains SGML and there is text selected
		"""

		if is_cursor_inside_sgml(self.view) and get_selection(self.view):
			return True

		return False

	def is_visible(self):
		"""
		Is this command visible in the command palette?
		True if the view contains SGML
		"""

		return is_se_file(self.view)
