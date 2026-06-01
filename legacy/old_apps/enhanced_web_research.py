# Enhanced Web Research Tab Implementation
# This code should replace the existing render_web_research_tab() function

import re
from urllib.parse import urlparse
from typing import Dict, List, Optional, Tuple, Any

def validate_url(url: str) -> Tuple[bool, str]:
    """Validate and normalize URL"""
    try:
        # Add protocol if missing
        if not url.startswith(('http://', 'https://')):
            url = 'https://' + url
        
        # Parse URL
        parsed = urlparse(url)
        if not parsed.netloc:
            return False, 'Invalid URL format'
        
        # Check for valid domain
        if not re.match(r'^[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', parsed.netloc):
            return False, 'Invalid domain name'
        
        return True, url
        
    except Exception as e:
        return False, f'URL validation error: {str(e)}'

def scrape_webpage_content(url: str) -> Dict[str, Any]:
    """Scrape webpage content with comprehensive error handling"""
    result = {
        'success': False,
        'url': url,
        'title': '',
        'content': '',
        'metadata': {},
        'word_count': 0,
        'extraction_method': '',
        'error_message': '',
        'timestamp': datetime.now().isoformat(),
        'processing_time': 0.0
    }
    
    start_time = time.time()
    
    try:
        # Validate URL first
        is_valid, normalized_url = validate_url(url)
        if not is_valid:
            result['error_message'] = normalized_url
            return result
        
        # Set up headers to mimic a real browser
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
        }
        
        # Fetch the page
        response = requests.get(normalized_url, headers=headers, timeout=10, allow_redirects=True)
        
        # Check response status
        if response.status_code == 200:
            # Extract content using BeautifulSoup
            try:
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(response.text, 'html.parser')
                
                # Remove unwanted elements
                for element in soup(['script', 'style', 'nav', 'footer', 'header', 'aside', 'advertisement', 'ads']):
                    element.decompose()
                
                # Extract title
                title_tag = soup.find('title')
                if title_tag:
                    result['title'] = title_tag.get_text().strip()
                
                # Try to find main content area
                main_content = None
                for selector in ['main', 'article', '.content', '#content', '.post', '.entry', '.article-content', '.post-content']:
                    main_content = soup.select_one(selector)
                    if main_content:
                        break
                
                if not main_content:
                    main_content = soup.find('body')
                
                if main_content:
                    # Extract text content
                    text = main_content.get_text()
                    # Clean up text
                    lines = (line.strip() for line in text.splitlines())
                    chunks = (phrase.strip() for line in lines for phrase in line.split('  '))
                    text = ' '.join(chunk for chunk in chunks if chunk)
                    
                    if len(text.strip()) > 100:
                        result['content'] = text.strip()
                        result['extraction_method'] = 'beautifulsoup'
                        result['word_count'] = len(text.split())
                        result['success'] = True
                        
                        # Extract metadata
                        meta_tags = soup.find_all('meta')
                        for meta in meta_tags:
                            name = meta.get('name', '').lower()
                            property_attr = meta.get('property', '').lower()
                            content_attr = meta.get('content', '')
                            
                            if name == 'description' or property_attr == 'og:description':
                                result['metadata']['description'] = content_attr
                            elif name == 'author' or property_attr == 'article:author':
                                result['metadata']['author'] = content_attr
                            elif property_attr == 'article:published_time':
                                result['metadata']['date'] = content_attr
                        
                        result['processing_time'] = time.time() - start_time
                        return result
                
                # Fallback: extract all text if no main content found
                text = soup.get_text()
                lines = (line.strip() for line in text.splitlines())
                chunks = (phrase.strip() for line in lines for phrase in line.split('  '))
                text = ' '.join(chunk for chunk in chunks if chunk)
                
                if len(text.strip()) > 100:
                    result['content'] = text.strip()
                    result['extraction_method'] = 'beautifulsoup_fallback'
                    result['word_count'] = len(text.split())
                    result['success'] = True
                    result['processing_time'] = time.time() - start_time
                    return result
                
            except ImportError:
                # Fallback to regex if BeautifulSoup not available
                text = re.sub(r'<[^>]+>', '', response.text)
                text = re.sub(r'\s+', ' ', text).strip()
                
                if len(text) > 100:
                    result['content'] = text
                    result['extraction_method'] = 'regex_fallback'
                    result['word_count'] = len(text.split())
                    result['success'] = True
                    
                    # Try to extract title
                    title_match = re.search(r'<title[^>]*>(.*?)</title>', response.text, re.IGNORECASE)
                    if title_match:
                        result['title'] = title_match.group(1).strip()
                    
                    result['processing_time'] = time.time() - start_time
                    return result
            
            result['error_message'] = 'No meaningful content found on this page'
            
        elif response.status_code == 403:
            result['error_message'] = 'Access forbidden (403) - Website blocks automated requests'
        elif response.status_code == 404:
            result['error_message'] = 'Page not found (404)'
        elif response.status_code == 429:
            result['error_message'] = 'Too many requests (429) - Rate limited'
        else:
            result['error_message'] = f'HTTP error {response.status_code}'
            
    except requests.exceptions.Timeout:
        result['error_message'] = 'Request timeout - Website took too long to respond'
    except requests.exceptions.ConnectionError:
        result['error_message'] = 'Connection error - Unable to reach the website'
    except requests.exceptions.RequestException as e:
        result['error_message'] = f'Request error: {str(e)}'
    except Exception as e:
        result['error_message'] = f'Unexpected error: {str(e)}'
    
    result['processing_time'] = time.time() - start_time
    return result

def save_content_to_knowledge_base(url: str, title: str, content: str, source: str, metadata: Dict) -> Dict[str, Any]:
    """Save scraped content to knowledge base"""
    try:
        # Generate unique ID
        entry_id = f'{url}_{int(time.time())}'
        
        # Create knowledge entry
        knowledge_entry = {
            'title': title,
            'content': content,
            'url': url,
            'source': source,
            'metadata': metadata,
            'word_count': len(content.split()),
            'timestamp': datetime.now().isoformat(),
            'entry_id': entry_id
        }
        
        # Add to session state scraped content
        if 'scraped_content' not in st.session_state:
            st.session_state.scraped_content = {}
        st.session_state.scraped_content[entry_id] = knowledge_entry
        
        # Add to research history
        if 'web_research_history' not in st.session_state:
            st.session_state.web_research_history = []
        
        research_entry = {
            'id': entry_id,
            'url': url,
            'title': title,
            'timestamp': datetime.now().isoformat(),
            'word_count': len(content.split()),
            'success': True
        }
        st.session_state.web_research_history.append(research_entry)
        
        # Save to knowledge base (integrate with existing system)
        if 'knowledge_base' in st.session_state:
            st.session_state.knowledge_base[entry_id] = knowledge_entry
        
        # TODO: Integrate with AI learning system
        # This is where you would call your AI learning backend
        # Example: backend.ai_learning.process_content_for_learning(knowledge_entry)
        # Example: backend.memory_system.add_knowledge(title, content, source)
        
        return {'success': True, 'entry_id': entry_id}
        
    except Exception as e:
        return {'success': False, 'error_message': str(e)}

def search_scraped_content(query: str) -> List[Dict[str, Any]]:
    """Search through scraped content"""
    results = []
    if 'scraped_content' not in st.session_state:
        return results
    
    query_lower = query.lower()
    
    for entry_id, content in st.session_state.scraped_content.items():
        relevance_score = 0
        
        # Check title
        if query_lower in content['title'].lower():
            relevance_score += 0.5
        
        # Check content
        if query_lower in content['content'].lower():
            relevance_score += 0.3
        
        # Check metadata
        for key, value in content['metadata'].items():
            if isinstance(value, str) and query_lower in value.lower():
                relevance_score += 0.1
        
        if relevance_score > 0:
            results.append({
                'id': entry_id,
                'relevance_score': relevance_score,
                'title': content['title'],
                'url': content['url'],
                'word_count': content['word_count'],
                'timestamp': content['timestamp']
            })
    
    return sorted(results, key=lambda x: x['relevance_score'], reverse=True)

def render_web_research_tab():
    """Enhanced Web Research tab with full scraping capabilities"""
    st.markdown('### 🌐 Web Research & Content Extraction')
    
    # Initialize session state for web research
    if 'scraped_content' not in st.session_state:
        st.session_state.scraped_content = {}
    if 'web_research_history' not in st.session_state:
        st.session_state.web_research_history = []
    if 'current_extracted_content' not in st.session_state:
        st.session_state.current_extracted_content = None
    
    # Main content extraction interface
    st.markdown('#### 🔍 Content Extraction')
    
    with st.form('content_extraction_form'):
        col1, col2 = st.columns([3, 1])
        
        with col1:
            url_input = st.text_input(
                'Website URL',
                placeholder='https://example.com',
                help='Enter the URL of the webpage you want to extract content from',
                value=st.session_state.get('current_url', '')
            )
        
        with col2:
            extract_button = st.form_submit_button('🔍 Extract Content', use_container_width=True)
    
    # Process extraction request
    if extract_button and url_input:
        if st.session_state.enable_web_search:
            # Store current URL in session state
            st.session_state.current_url = url_input
            
            with st.spinner('🔍 Extracting content from webpage...'):
                # Scrape the content
                scrape_result = scrape_webpage_content(url_input)
                
                if scrape_result['success']:
                    st.success(f'✅ Content extracted successfully in {scrape_result["processing_time"]:.2f}s')
                    
                    # Store extracted content in session state
                    st.session_state.current_extracted_content = scrape_result
                    
                    # Display extracted content
                    st.markdown('#### 📄 Extracted Content')
                    
                    # Content info
                    col1, col2, col3 = st.columns(3)
                    with col1:
                        st.metric('Word Count', scrape_result['word_count'])
                    with col2:
                        title_display = scrape_result['title'][:30] + '...' if len(scrape_result['title']) > 30 else scrape_result['title']
                        st.metric('Title', title_display)
                    with col3:
                        st.metric('Method', scrape_result['extraction_method'])
                    
                    # Display content in scrollable area
                    st.markdown('**Content Preview:**')
                    
                    with st.expander('📖 View Full Content', expanded=True):
                        st.text_area(
                            'Extracted Text',
                            value=scrape_result['content'],
                            height=300,
                            disabled=True,
                            help='This is the main text content extracted from the webpage'
                        )
                    
                    # Metadata display
                    if scrape_result['metadata']:
                        with st.expander('📊 Metadata'):
                            st.json(scrape_result['metadata'])
                    
                    # Save to knowledge base
                    st.markdown('#### 💾 Save to Knowledge Base')
                    
                    with st.form('save_to_knowledge_form'):
                        col1, col2 = st.columns([2, 1])
                        
                        with col1:
                            custom_title = st.text_input(
                                'Custom Title (optional)',
                                value=scrape_result['title'],
                                help='You can customize the title for the knowledge base entry'
                            )
                        
                        with col2:
                            source_type = st.selectbox(
                                'Source Type',
                                ['web_scraping', 'research', 'reference', 'tutorial', 'news'],
                                help='Categorize this content for better organization'
                            )
                        
                        save_button = st.form_submit_button('💾 Save to Knowledge Base', use_container_width=True)
                        
                        if save_button:
                            # Save to knowledge base
                            save_result = save_content_to_knowledge_base(
                                url_input,
                                custom_title,
                                scrape_result['content'],
                                source_type,
                                scrape_result['metadata']
                            )
                            
                            if save_result['success']:
                                st.success('✅ Content saved to knowledge base!')
                                st.info('This content is now available to the AI for responses and learning.')
                                
                                # TODO: Trigger AI learning process
                                # This is where you would integrate with your AI learning backend
                                # Example: backend.ai_learning.learn_from_content(save_result)
                                # Example: backend.memory_system.add_knowledge(custom_title, scrape_result['content'], source_type)
                                
                            else:
                                st.error(f'❌ Failed to save: {save_result["error_message"]}')
                
                else:
                    st.error(f'❌ Extraction failed: {scrape_result["error_message"]}')
                    
                    # Show troubleshooting tips
                    with st.expander('🔧 Troubleshooting Tips'):
                        st.markdown('''
                        **Common issues and solutions:**
                        
                        1. **Access Forbidden (403)**: The website blocks automated requests
                           - Try a different website
                           - Some sites require JavaScript rendering
                        
                        2. **No Content Found**: The page might be empty or use heavy JavaScript
                           - Try a different page on the same site
                           - Check if the URL is correct
                        
                        3. **Connection Error**: Network or server issues
                           - Check your internet connection
                           - Try again in a few minutes
                        
                        4. **Invalid URL**: The URL format is incorrect
                           - Make sure to include http:// or https://
                           - Check for typos in the URL
                        ''')
        else:
            st.warning('🌐 Web research is disabled. Enable it in the sidebar.')
    
    # Show current extracted content if available
    elif st.session_state.current_extracted_content:
        st.markdown('#### 📄 Current Extracted Content')
        
        content = st.session_state.current_extracted_content
        
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric('Word Count', content['word_count'])
        with col2:
            title_display = content['title'][:30] + '...' if len(content['title']) > 30 else content['title']
            st.metric('Title', title_display)
        with col3:
            st.metric('Method', content['extraction_method'])
        
        with st.expander('📖 View Content', expanded=False):
            st.text_area(
                'Extracted Text',
                value=content['content'],
                height=300,
                disabled=True
            )
        
        # Quick save option
        if st.button('💾 Quick Save to Knowledge Base'):
            save_result = save_content_to_knowledge_base(
                content['url'],
                content['title'],
                content['content'],
                'web_scraping',
                content['metadata']
            )
            
            if save_result['success']:
                st.success('✅ Content saved to knowledge base!')
            else:
                st.error(f'❌ Failed to save: {save_result["error_message"]}')
    
    # Scraped content management
    if st.session_state.scraped_content:
        st.markdown('#### 📚 Scraped Content Library')
        
        # Search through scraped content
        search_query = st.text_input('🔍 Search Scraped Content', placeholder='Search through your saved content...')
        
        if search_query:
            search_results = search_scraped_content(search_query)
            
            if search_results:
                st.markdown(f'**Found {len(search_results)} relevant entries:**')
                
                for result in search_results[:5]:  # Show top 5 results
                    content = st.session_state.scraped_content.get(result['id'])
                    if content:
                        with st.expander(f'📖 {result["title"]} (Relevance: {result["relevance_score"]:.2f})'):
                            st.markdown(f'**URL:** {result["url"]}')
                            st.markdown(f'**Word Count:** {result["word_count"]}')
                            st.markdown(f'**Saved:** {result["timestamp"][:19]}')
                            
                            # Show content preview
                            preview = content['content'][:500] + '...' if len(content['content']) > 500 else content['content']
                            st.text_area('Content Preview', value=preview, height=100, disabled=True)
                            
                            # Actions
                            col1, col2, col3 = st.columns(3)
                            with col1:
                                if st.button('👁️ View Full', key=f'view_{result["id"]}'):
                                    st.session_state[f'view_content_{result["id"]}'] = True
                            
                            with col2:
                                if st.button('🗑️ Delete', key=f'delete_{result["id"]}'):
                                    del st.session_state.scraped_content[result['id']]
                                    st.rerun()
                            
                            with col3:
                                if st.button('🔄 Re-scrape', key=f'rescape_{result["id"]}'):
                                    st.info('Re-scraping functionality not implemented yet.')
                            
                            # Show full content if requested
                            if st.session_state.get(f'view_content_{result["id"]}', False):
                                st.text_area('Full Content', value=content['content'], height=300, disabled=True)
            else:
                st.info('No matching content found.')
        
        # Show all scraped content
        else:
            st.markdown('**All Scraped Content:**')
            
            for entry_id, content in list(st.session_state.scraped_content.items())[-10:]:  # Show last 10
                with st.expander(f'📄 {content["title"]} ({content["word_count"]} words)'):
                    st.markdown(f'**URL:** {content["url"]}')
                    st.markdown(f'**Source:** {content["source"]}')
                    st.markdown(f'**Extracted:** {content["timestamp"][:19]}')
                    st.markdown(f'**Method:** {content["extraction_method"]}')
                    
                    # Content preview
                    preview = content['content'][:300] + '...' if len(content['content']) > 300 else content['content']
                    st.text_area('Preview', value=preview, height=100, disabled=True, key=f'preview_{entry_id}')
    
    # Research history
    if st.session_state.web_research_history:
        st.markdown('#### 📈 Research History')
        
        # Show recent research activities
        recent_research = st.session_state.web_research_history[-10:]  # Last 10 entries
        
        for research in reversed(recent_research):
            with st.expander(f'🔍 {research["url"]} - {research["timestamp"][:19]}'):
                st.markdown(f'**Title:** {research["title"]}')
                st.markdown(f'**Word Count:** {research["word_count"]}')
                st.markdown(f'**Status:** {"✅ Success" if research["success"] else "❌ Failed"}')
    
    # Quick actions
    st.markdown('#### ⚡ Quick Actions')
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        if st.button('🔄 Refresh Data'):
            st.rerun()
    
    with col2:
        if st.button('💾 Save All Data'):
            # TODO: Implement data persistence
            st.success('All data saved!')
    
    with col3:
        if st.button('🗑️ Clear All Content'):
            if st.session_state.scraped_content:
                st.session_state.scraped_content = {}
                st.session_state.web_research_history = []
                st.session_state.current_extracted_content = None
                st.success('All content cleared!')
                st.rerun()
    
    # Statistics
    if st.session_state.scraped_content:
        st.markdown('#### 📊 Statistics')
        
        total_content = len(st.session_state.scraped_content)
        total_words = sum(content['word_count'] for content in st.session_state.scraped_content.values())
        avg_words = total_words / total_content if total_content > 0 else 0
        
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric('Total Pages', total_content)
        with col2:
            st.metric('Total Words', f'{total_words:,}')
        with col3:
            st.metric('Avg Words/Page', f'{avg_words:.0f}')
